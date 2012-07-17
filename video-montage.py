#!/usr/bin/env python

import argparse
import os
import os.path
import re
import subprocess
import shutil
import tempfile

from collections import namedtuple
from datetime import timedelta
from multiprocessing.pool import ThreadPool

from which import which, CommandNotFoundException

__author__ = 'John O\'Connor'
__version__ = '0.1'

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

    def start(self):
        if not self.config.tempdir:
            tempdir = tempfile.mkdtemp()
            cleanup = True
        else:
            tempdir = self.config.tempdir
            cleanup = False

        p = ThreadPool()

        for video_file in self.config.video_files:
            video = self._video(video_file)
            outdir = self.config.outdir or os.path.dirname(video.filename)
            outprefix = os.path.join(outdir, video.basename)
            tempprefix = os.path.join(tempdir, video.basename)
            montage_file = "%s.%s" % (outprefix, self.config.format)
            if os.path.exists(montage_file):
                os.remove(montage_file)

            thumbnails = self.create_thumbnails(video, tempprefix)
            p.map(self._resize_thumbnails, thumbnails)
            self._create_montage(montage_file, thumbnails)
            self._apply_label(montage_file, video)
            map(os.remove, thumbnails)
            if cleanup:
                shutil.rmtree(tempdir)

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

    def _resize_thumbnails(self, thumbnail):
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
                                self.config.format),
                                        stderr=subprocess.STDOUT)
        ffmpeg.wait()
        return ["%s_%03d.%s" % (outprefix, i, self.config.format)
                    for i in range(1, vframes + 1)]


def main():
    parser = argparse.ArgumentParser(description="Create a montage of frames from a video file")

    parser.add_argument('video_files', metavar='video_file', nargs='+',
            help='List video files to montage')

    parser.add_argument('--thumbnails', '-n', metavar='N', default=25, type=int,
            help='Number of thumbnails to include')

    parser.add_argument('--thumbsize', '-s', metavar='N', default=202, type=int,
            help='Size of individual thumbnails')

    parser.add_argument('--outdir', '-d', metavar='PATH', default=None,
            help='Output directory for montage images defaults to same '
                 'directory as the input video file.')

    parser.add_argument('--start-seconds', '-ss', metavar='N', default=30, type=int,
            help='Start reading from video at specified offset in seconds')

    parser.add_argument('--format', '-f', default='png',
            choices=('png', 'gif', 'jpg'),
            help='Output format for montage image')

    parser.add_argument('--tempdir', '-t', metavar='PATH', default=None,
            help='Temporary directory for processing')

    parser.add_argument('--verbose', '-v', default=False, action='store_true',
            help='Show more verbose logging information')

    parser.add_argument('--background-color', '-bg', default='black',
            help='Background color for the montage.')

    args = parser.parse_args()
    if not args or args.video_files is None:
        parser.print_help()
        raise SystemExit(1)

    m = VideoMontager(args)
    m.start()

if __name__ == '__main__':
    main()
