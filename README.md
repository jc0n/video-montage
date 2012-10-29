video-montage
=============

Generate a montage of video frames (aka. screen captures or screencaps) from video files or a directory of video files. Produces a png, gif, or jpeg image with thumbnails of each frame grouped into a montage.

![Example Image](https://raw.github.com/jc0n/video-montage/master/example.png)

## Install

### Dependencies

- Python 2.7+ http://python.org/
- FFmpeg http://ffmpeg.org/
- ImageMagick http://www.imagemagick.org/script/index.php

### Windows Binary Packages (python not required):

- Download pre-built binary package from github: https://github.com/jc0n/video-montage/downloads
- Install ImageMagick Binaries from: http://www.imagemagick.org/script/binary-releases.php
- Install FFmpeg Binaries from: http://ffmpeg.zeranoe.com/builds/
- Install VC++ 2008 Redist: http://www.microsoft.com/en-us/download/confirmation.aspx?id=29

### From Source (with Python installed):

```
git clone git://github.com/jc0n/video-montage.git
cd video-montage
pip install -r requirements.txt
python setup.py install
```

#### Installing dependencies

##### Ubuntu
```
apt-get install ffmpeg imagemagick
```

##### Solaris 11
```
pkg install image/imagemagick
wget http://mirror.opencsw.org/opencsw/pkgutil.pkg
pkgadd -d pkgutil.pkg all
/opt/csw/bin/pkgutil -i CSWffmpeg
```



## Usage

Basic Usage:
`video-montage video1.mkv video2.avi`

Put screencaps in a separate directory:
`video-montage -d screens/ videos/`

Process all videos in subdirectories recursively:
`video-montage -d screens/ -r videos/`

