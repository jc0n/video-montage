video-montage
=============

Generate a montage of video frames (aka. screen captures or screencaps) from video files or a directory of video files. Produces a png, gif, or jpeg image with thumbnails of each frame grouped into a montage.

## Install

#### Binary Packages (python not required):

- Download pre-built binary package from github: https://github.com/jc0n/video-montage/downloads
- Install VC++ 2008 Redist: http://www.microsoft.com/en-us/download/confirmation.aspx?id=29

#### From Source, with Python installed:

```
git clone git://github.com/jc0n/video-montage.git
cd video-montage
pip install -r requirements.txt
python setup.py install
```

## Usage

Basic Usage:
`video-montage video1.mkv video2.avi`

Put screencaps in a separate directory:
`video-montage -d screens/ videos/`

Process all videos in subdirectories recursively:
`video-montage -d screens/ -r videos/`

