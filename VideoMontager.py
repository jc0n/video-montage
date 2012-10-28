"""
VideoMontager is a simple class which provides a wrapper around ffmpeg and
imagemagic using them to create a montage of frames from specified video files.
"""

import os
import os.path
import re
import shutil
import subprocess
import sys
import tempfile

from collections import namedtuple
from datetime import timedelta
from multiprocessing.pool import ThreadPool

from which import which, CommandNotFoundException

#TODO: add error handling
#TODO: add abilty to specify directories
#TODO: replace print to stdout with proper logging

__author__ = 'John O\'Connor'
__version__ = '0.1.1'

def command(cmd):
    which(cmd)
    def wrapper(argstr, **kwargs):
        fullcmd = cmd + ' %s' % argstr
        return subprocess.Popen(fullcmd, shell=True, **kwargs)
    return wrapper

ffmpeg_cmd = command('ffmpeg')
ffprobe_cmd = command('ffprobe')
montage_cmd = command('montage')
convert_cmd = command('convert')

_VIDEO_EXTENSIONS = frozenset(('3gp', 'asf', 'asx', 'avi', 'axv', 'dif', 'dl',
                               'dv', 'fli', 'flv', 'gl', 'lsf', 'lsx', 'mkv',
                               'mng', 'mov', 'movie', 'mp4', 'mpe', 'mpeg',
                               'mpg', 'mpv', 'mxu', 'ogv', 'qt', 'ts', 'webm',
                               'wm', 'wmv', 'wmx', 'wvx'))

_VIDEO_RE = re.compile('''
    Duration:\s+(?P<hours>\d{2}):
                (?P<minutes>\d{2}):
                (?P<seconds>\d{2})\.\d{2},
    .+
    Video:\s+(?P<codec>[^,]+),[^,]+,\s+(?P<resolution>\d+x\d+)
    .+
    (?P<fps>\d+)\s+tbr,
    ''', re.VERBOSE | re.DOTALL | re.MULTILINE)


class VideoMontager:
    Video = namedtuple('Video', 'filename basename resolution codec duration fps')

    def __init__(self, config):
        self.config = config
        self._pool = ThreadPool()

    def start(self):
        self._process_videos(self.config.video_files)

    def _filter_video_files(self, video_file):
        name, ext = os.path.splitext(video_file)
        return ext[1:] in _VIDEO_EXTENSIONS

    def _process_videos(self, video_files):
        if not self.config.tempdir:
            tempdir = tempfile.mkdtemp()
            cleanup = True
        else:
            tempdir = self.config.tempdir
            cleanup = False

        print "Creating tempdir %s" % tempdir
        video_files = filter(self._filter_video_files, video_files)
        for video_file in video_files:
            video = self._video(video_file)
            tempprefix = os.path.join(tempdir, video.basename)
            self._process_video(video, tempprefix)

        print "Cleaning up"
        if cleanup:
            shutil.rmtree(tempdir)

    def _process_video(self, video, tempprefix):
        outdir = self.config.outdir or os.path.dirname(video.filename)
        outprefix = os.path.join(outdir, video.basename)
        montage_file = "%s.%s" % (outprefix, self.config.format)
        if os.path.exists(montage_file):
            if not self.config.overwrite:
                # TODO: add log entry
                # montage image file already exists
                print "Montage Exists. Skipping"
                return
            os.remove(montage_file)

        print "Creating thumbnails for %s" % video.basename
        thumbnails = self.create_thumbnails(video, tempprefix)
        print "Resizing thumbnails"
        self._pool.map(self._resize_thumbnail, thumbnails)
        print "Creating montage %s" % montage_file
        self._create_montage(montage_file, thumbnails)
        self._apply_label(montage_file, video)
        map(os.remove, thumbnails)

    def _video(self, video_file):
        ffprobe = ffprobe_cmd('"%s"' % video_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
        stdout, stderr = ffprobe.communicate()
        v = _VIDEO_RE.search(stdout).groupdict()
        return self.Video(filename=video_file,
                          basename=os.path.basename(video_file),
                          codec=v['codec'],
                          resolution=v['resolution'],
                          fps=int(v['fps']),
                          duration=timedelta(
                              hours=int(v['hours']),
                              minutes=int(v['minutes']),
                              seconds=int(v['seconds'])))

    def _create_montage(self, montage_file, thumbnails):
        montage_cmd('-background %s '
                    '-borderwidth 0 -geometry "+1+1" '
                    '"%s" "%s"' % (self.config.background_color,
                                   '" "'.join(thumbnails[1:]),
                                   montage_file)).wait()

    def _apply_label(self, montage_file, video):
        label = 'Filename: %s | Codec: %s | Resolution: %s | Length %s | FPS: %d' % (
                    video.basename,
                    video.codec,
                    video.resolution,
                    str(video.duration),
                    video.fps)

        convert_cmd('-gravity North -splice 0x28 -background %s '
                    '-fill white -pointsize 12 '
                    '-annotate +0+6 '
                    '"%s" "%s" "%s"' % (self.config.background_color,
                                        label,
                                        montage_file,
                                        montage_file)).wait()

    def _resize_thumbnail(self, thumbnail):
        convert = convert_cmd('-quality 100 '
                    '-resize "%d" '
                    '"%s" "%s"' % (
                        self.config.thumbsize,
                        thumbnail,
                        thumbnail))
        convert.wait()

    def create_thumbnails(self, video, outprefix):
        vframes = self.config.thumbnails + 1
        interval = (video.duration.total_seconds() - 60) / self.config.thumbnails
        ffmpeg = ffmpeg_cmd('-y -i "%s"'
                            ' -ss %d'
                            ' -r "1/%d"'
                            ' -vframes %d'
                            ' -bt 100000000 '
                            ' "%s_%%03d.%s"' % (
                                video.filename,
                                self.config.start_seconds,
                                interval,
                                vframes,
                                outprefix,
                                self.config.format),)
        ffmpeg.wait()
        return ["%s_%03d.%s" % (outprefix, i, self.config.format)
                    for i in range(1, vframes + 1)]