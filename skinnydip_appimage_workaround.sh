#! /bin/sh
SCRIPT=`realpath $0`
SCRIPTPATH=`dirname $SCRIPT`
unset LD_LIBRARY_PATH
unset PYTHONHOME
unset PYTHONPATH
unset PERLLIB
exec /usr/bin/python2.7 $SCRIPTPATH/skinnydip.py $@
