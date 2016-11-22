#! /usr/bin/env python

"""distutils metadata/installer for txfixtures"""


import os.path
from distutils.core import setup

import txfixtures


def get_version():
    return '.'.join(
        str(component) for component in txfixtures.__version__[0:3])


def get_long_description():
    readme_path = os.path.join(
        os.path.dirname(__file__), 'README')
    return open(readme_path).read()


setup(
    name='txfixtures',
    maintainer='Martin Pool',
    maintainer_email='mbp@canonical.com',
    url='https://launchpad.net/txfixtures',
    description=('Treat Twisted applications as Python test fixtures'),
    long_description=get_long_description(),
    version=get_version(),
    classifiers=["License :: OSI Approved :: GNU General Public License (GPL)"],
    packages=['txfixtures'],
    requires=[
        'fixtures',
        'testtools',
        'twisted',
        ],
    )
