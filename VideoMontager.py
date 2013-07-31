"""
VideoMontager provides a wrapper around FFMpeg and ImageMagic using them
to create a montage of frame thumbnails from specified videos.
"""

import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile

from collections import namedtuple
from datetime import timedelta

from progressbar import ProgressBar, SimpleProgress, Bar
from which import which

__author__ = 'John O\'Connor'
__version__ = '0.1.7'

__all__ = ('VideoMontager', )

log = logging.getLogger(__name__)

def command(cmd, executor=subprocess.check_call):
    which(cmd)
    def wrapper(argstr, executor=executor, **kwargs):
        fullcmd = cmd + ' %s' % argstr
        log.debug('Executing shell command: %s' % fullcmd)
        return executor(fullcmd, shell=True, **kwargs)
    return wrapper


def quote_filename(name):
    return '"%s"' % name.replace('"', '\\"')

def create_convert_command():
    if platform.system() == "Windows":
        # C:\Windows\System32\convert.EXE will usually match
        # first unless we look elsewhere.
        montage_path = os.path.dirname(which('montage.exe'))
        return command(os.path.join(montage_path, 'convert.exe'))
    else:
        return command('convert')

def check_ffmpeg_supports_nostdin():
    ffmpeg = FFMPEG('-nostdin', executor=subprocess.Popen,
                stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    stdout, stderr = ffmpeg.communicate()
    return 'Unrecognized option' not in stdout

CONVERT = create_convert_command()
MONTAGE = command('montage')
FFPROBE = command('ffprobe', subprocess.Popen)
FFMPEG = command('ffmpeg', subprocess.Popen)

FFMPEG_SUPPORTS_NOSTDIN = check_ffmpeg_supports_nostdin()
FFMPEG_STDIO_READ_BUFSIZE = 80

VIDEO_EXTENSIONS = frozenset(('avi', 'flv', 'f4v', 'mkv', 'mng', 'mov',
                              'movie', 'mp4', 'mpe', 'mpeg',
                              'mpg', 'mpv', 'ogv', 'ts', 'wmv'))

VIDEO_EXPR = re.compile(r'''
    Duration:\s+(?P<hours>\d{2}):
                (?P<minutes>\d{2}):
                (?P<seconds>\d{2})\.\d{2},
    .+
    Video:\s+(?P<codec>[^,]+),[^,]+,\s+(?P<resolution>\d+x\d+)
    .+
    (?P<fps>\d+)\s+tbr,
    ''', re.VERBOSE | re.DOTALL | re.MULTILINE)

FRAME_EXPR = re.compile(b'frame=\s*(\d+)', re.MULTILINE)

class Thumbnail(namedtuple('Thumbnail', 'filename time')):
    def __repr__(self):
        return self.path
    __str__ = __repr__

Video = namedtuple('Video', 'filename basename resolution codec duration fps')

class InvalidVideoFileException(Exception):
    """
    Raised when video file contains invalid data.
    """
    pass


class VideoProcessingException(Exception):
    """
    Raised when an error occurs processing a video file
    """
    pass


class VideoMontager(object):
    """
    VideoMontager Class

    Provides a simple wrapper around ffmpeg and imagemagic tools and uses
    them to process video files and directories with video files into a
    montage of screenshots from various intervals in each video.
    """
    def __init__(self, video_files, **kwargs):
        self.video_files = video_files
        self.background_color = kwargs.pop('background_color', 'black')
        self.ffmpeg_args = kwargs.pop('ffmpeg_args', '')
        self.format = kwargs.pop('format', 'jpg')
        self.include_timestamps = kwargs.pop('include_timestamps', True)
        self.label_color = kwargs.pop('label_color', 'white')
        self.montage_args = kwargs.pop('montage_args', '')
        self.outdir = kwargs.pop('outdir', None)
        self.overwrite = kwargs.pop('overwrite', False)
        self.progress = kwargs.pop('progress', False)
        self.recursive = kwargs.pop('recursive', False)
        self.resolution = kwargs.pop('resolution', '2560x1600')
        self.start_seconds = kwargs.pop('start_seconds', 0)
        self.tile = kwargs.pop('tile', None)
        if self.tile:
            if 'x' in self.tile:
                n, m = map(int, self.tile.split('x', 1))
            else:
                m = n = int(self.tile)
            self.thumbnail_count = n * m
        else:
            self.thumbnail_count = kwargs.pop('thumbnail_count', 25)

    def process_videos(self):
        "Begin processing video files."
        self.tempdir = tempfile.mkdtemp()
        log.debug("Created temp directory: %s", self.tempdir)
        try:
            for video_file in self._get_video_files():
                try:
                    self._process_video_file(video_file)
                except InvalidVideoFileException:
                    continue
        except KeyboardInterrupt: # mostly for ctrl-c
            pass
        finally:
            log.debug("Removing temp directory: %s", self.tempdir)
            shutil.rmtree(self.tempdir)

    def _make_video(self, video_file):
        ffprobe = FFPROBE('"%s"' % video_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT)
        stdout, stderr = ffprobe.communicate()
        m = VIDEO_EXPR.search(stdout)
        if not m:
            log.error("ffprobe failed for file %s" % video_file)
            raise InvalidVideoFileException(video_file)
        v = m.groupdict()
        duration = timedelta(hours=int(v['hours']),
                             minutes=int(v['minutes']),
                             seconds=int(v['seconds']))
        return Video._make((video_file,
                            os.path.basename(video_file),
                            v['resolution'],
                            v['codec'],
                            duration,
                            int(v['fps'])))


    def _get_video_files(self):
        """
        A generator which produces all video files to process based on
        specified input files and directories.
        """
        def is_video(filepath):
            if not os.path.exists(filepath):
                return False
            if not os.path.isfile(filepath):
                return False
            if not os.path.getsize(filepath):
                return False
            name, ext = os.path.splitext(filepath)
            return ext[1:].lower() in VIDEO_EXTENSIONS

        for video_file in self.video_files:
            if os.path.isdir(video_file):
                if self.recursive:
                    for root, dirs, files in os.walk(video_file, topdown=True):
                        for filename in sorted(files):
                            filepath = os.path.join(root, filename)
                            if is_video(filepath):
                                yield filepath
                else:
                    for filename in sorted(os.listdir(video_file)):
                        filepath = os.path.join(video_file, filename)
                        if is_video(filepath):
                            yield filepath
            elif is_video(video_file):
                yield video_file
            else:
                log.warning("Invalid video file specified: %s" % video_file)
                raise InvalidVideoFileException(video_file)

    def _create_montage(self, montage_file, thumbnails):
        log.info("Creating montage %s" % montage_file)

        montage_args = ['-background %s' % self.background_color]
        montage_args.append('-borderwidth 0 -geometry "+1+1"')
        if self.montage_args:
            montage_args.append(self.montage_args)
        montage_args.extend(quote_filename(t.filename) for t in thumbnails)
        montage_args.append(montage_file)
        MONTAGE(' '.join(montage_args))
        CONVERT('-resize "%s" %s %s' % (
            self.resolution, montage_file, montage_file))

    def _apply_header_label(self, montage_file, video):
        log.debug("Applying label for %s" % montage_file)

        label = '%s | Codec: %s | Resolution: %s | Length %s' % (
            video.basename, video.codec, video.resolution, str(video.duration))
        CONVERT('-gravity North -splice 0x28 -background %s '
                '-fill %s -pointsize 12 -annotate +0+6 "%s" %s %s' % (
                    self.background_color, self.label_color, label,
                    montage_file, montage_file))

    def _process_video_file(self, video_file):
        outdir = self.outdir or os.path.dirname(video_file)
        outprefix = os.path.join(outdir, os.path.basename(video_file))
        montage_file = "%s.%s" % (outprefix, self.format)
        if os.path.exists(montage_file):
            if not self.overwrite:
                msg = "Found existing montage file %s, skipping." % montage_file
                log.info(msg)
                return
            os.remove(montage_file)

        video = self._make_video(video_file)
        tempprefix = os.path.join(self.tempdir, video.basename)
        thumbnails = self._create_thumbnails(video, tempprefix)

        montage_file = quote_filename(montage_file)
        self._create_montage(montage_file, thumbnails)
        self._apply_header_label(montage_file, video)

    def _create_thumbnails(self, video, outprefix):
        log.info("Creating thumbnails for %s" % video.basename)

        def add_thumbnail_timestamp(thumbnail):
            filename = quote_filename(thumbnail.filename)
            hours, r = divmod(thumbnail.time.total_seconds(), 3600)
            minutes, seconds = divmod(r, 60)
            label = '%02d:%02d:%02d' % (hours, minutes, seconds)
            CONVERT('-gravity northeast -pointsize 36 '
                    '-stroke black -strokewidth 6 -annotate +6+10 "%s" '
                    '-stroke white -strokewidth 1 '
                    '-fill white -annotate +10+10 "%s" '
                    '%s %s' % (label, label, filename, filename))

        interval = ((video.duration.total_seconds() - self.start_seconds)
                        / self.thumbnail_count)

        args = ['-y -ss %d -i' % self.start_seconds]
        args.append(quote_filename(video.filename))
        args.append('-r "1/%d"' % interval)
        args.append('-vframes %d -bt 100000000' % (self.thumbnail_count + 1))
        args.append(quote_filename('%s_%%03d.%s' % (outprefix, self.format)))
        if self.ffmpeg_args:
            args.append(self.ffmpeg_args)
        if FFMPEG_SUPPORTS_NOSTDIN:
            args.append('-nostdin')

        ffmpeg = FFMPEG(' '.join(args),
                stderr=subprocess.STDOUT,
                stdout=subprocess.PIPE)

        # whether or not to show a progress bar
        if self.progress:
            progress = ProgressBar(
                    maxval=self.thumbnail_count,
                    widgets=[SimpleProgress(), Bar()])
            progress.start()

        # consume stdout output from ffmpeg and extract progress information
        b = bytearray(FFMPEG_STDIO_READ_BUFSIZE)
        index, next_index = 0, 0
        thumbnails = []
        while True:
            chunk = ffmpeg.stdout.read(FFMPEG_STDIO_READ_BUFSIZE)
            if not chunk:
                break
            b += chunk
            m = FRAME_EXPR.search(b)
            if m is None:
                continue
            next_index = int(m.group(1))
            if next_index <= index:
                b[:] = b''
                continue
            index = next_index
            if index < 1:
                # skip the first thumbnail because ffmpeg always creates a duplicate
                continue
            filename = "%s_%03d.%s" % (outprefix, index, self.format)
            if not os.path.exists(filename):
                error = "Failed creating thumbnail %d (%s)." % (index, filename)
                raise VideoProcessingException(error)

            seconds = self.start_seconds + (interval * (index - 2))
            thumbnail = Thumbnail(filename, timedelta(seconds=seconds))
            if self.include_timestamps:
                add_thumbnail_timestamp(thumbnail)
            thumbnails.append(thumbnail)
            if self.progress:
                progress.update(max(0, index - 1))

        if self.progress:
            progress.finish()

        ffmpeg.wait()
        if ffmpeg.returncode != 0:
            raise subprocess.CalledProcessError('ffmpeg', ffmpeg.returncode)

        return thumbnails
