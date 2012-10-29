video-montage
=============

Generate a montage of video frames from video files or a directory of video files.

## Install

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

