#!/usr/bin/env python

from distutils.core import setup

import VideoMontager

setup(name='video-montage',
      version=VideoMontager.__version__,
      description='A tool for generating a montage of frames'
                  'from a video file.',
      author='John O\'Connor',
      url='https://github.com/jc0n/video-montage',
      py_modules=['VideoMontager'],
      scripts=['bin/video-montage'])

