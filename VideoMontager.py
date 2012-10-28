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
#TODO: allow silent operation

__author__ = 'John O\'Connor'
__version__ = '0.1.2'

__all__ = ('VideoMontager', )

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


Video = namedtuple('Video', 'filename basename resolution codec duration fps')

class VideoMontager(object):
    """
    VideoMontager Class

    Provides a simple wrapper around ffmpeg and imagemagic tools and uses them to
    process video files and directories with video files into a montage of screenshots from
    various intervals in each video file.
    """
    def __init__(self, config):
        self.config = config
        self._pool = ThreadPool()

    # TODO: create two classes. one which exposes the public methods and another
    #       internal class which contains all internal methods
    def process_videos(self):
        "Start processing video files."
        if not self.config.tempdir:
            tempdir = tempfile.mkdtemp()
            cleanup = True
        else:
            tempdir = self.config.tempdir
            cleanup = False

        print "Creating tempdir %s" % tempdir
        for video in self._get_videos():
            tempprefix = os.path.join(tempdir, video.basename)
            self._process_video(video, tempprefix)

        print "Cleaning up"
        if cleanup:
            shutil.rmtree(tempdir)

    def _video(self, video_file):
        ffprobe = ffprobe_cmd('"%s"' % video_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
        stdout, stderr = ffprobe.communicate()
        v = _VIDEO_RE.search(stdout).groupdict()
        return Video(filename=video_file,
                     basename=os.path.basename(video_file),
                     codec=v['codec'],
                     resolution=v['resolution'],
                     fps=int(v['fps']),
                     duration=timedelta(
                              hours=int(v['hours']),
                              minutes=int(v['minutes']),
                              seconds=int(v['seconds'])))


    def _get_videos(self):
        """
        Generator for producing Video objects from specified files and directories
        """
        def is_video(filepath):
            if not os.path.exists(filepath):
                return False
            if not os.path.isfile(filepath):
                return False
            name, ext = os.path.splitext(filepath)
            return ext[1:] in _VIDEO_EXTENSIONS

        for video_file in self.config.video_files:
            if os.path.isdir(video_file):
                if self.config.recursive:
                    for root, dirs, files in os.walk(video_file):
                        for filename in sorted(files):
                            filepath = os.path.join(root, filename)
                            if is_video(filepath):
                                yield self._video(filepath)
                else:
                    for filename in sorted(os.listdir(video_file)):
                        filepath = os.path.join(video_file, filename)
                        if is_video(filepath):
                            yield self._video(filepath)
            elif is_video(video_file):
                yield self._video(video_file)
            else:
                # argument not a video file
                # TODO(jcon): error logging / notification
                pass

    def _process_video(self, video, tempprefix):
        """
        Process individual Video object.
        """
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
        thumbnails = self._create_thumbnails(video, tempprefix)
        print "Resizing thumbnails"
        self._pool.map(self._resize_thumbnail, thumbnails)
        print "Creating montage %s" % montage_file
        self._create_montage(montage_file, thumbnails)
        self._apply_label(montage_file, video)
        for thumbnail in thumbnails:
            os.remove(thumbnail)

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

    def _create_thumbnails(self, video, outprefix):
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
