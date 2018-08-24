#!/usr/bin/env python
# FROM: https://www.stavros.io/posts/python-fuse-filesystem/
# (C) Stavros Korokithakis
# licensed under the BSD license

from __future__ import with_statement

import os
import sys
import errno

# from fuse import FUSE, FuseOSError, Operations
from fusepy import FUSE, FuseOSError, Operations, fuse_get_context


class Passthrough(Operations):
    def __init__(self, root):
        self.root = root

    # Helpers
    # =======

    def _full_path(self, partial):
        partial = partial.lstrip("/")
        path = os.path.join(self.root, partial)
        return path

    # Filesystem methods
    # ==================

    def access(self, path, mode):
        full_path = self._full_path(path)
        if not os.access(full_path, mode):
            raise FuseOSError(errno.EACCES)

    def chmod(self, path, mode):
        full_path = self._full_path(path)
        return os.chmod(full_path, mode)

    def chown(self, path, uid, gid):
        full_path = self._full_path(path)
        return os.chown(full_path, uid, gid)

    def getattr(self, path, fh=None):
        full_path = self._full_path(path)
        st = os.lstat(full_path)
        return dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

    def readdir(self, path, fh):
        full_path = self._full_path(path)

        dirents = ['.', '..']
        if os.path.isdir(full_path):
            dirents.extend(os.listdir(full_path))
        for r in dirents:
            yield r

    def readlink(self, path):
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            # Path name is absolute, sanitize it.
            return os.path.relpath(pathname, self.root)
        else:
            return pathname

    def mknod(self, path, mode, dev):
        return os.mknod(self._full_path(path), mode, dev)

    def rmdir(self, path):
        full_path = self._full_path(path)
        return os.rmdir(full_path)

    def mkdir(self, path, mode):
        return os.mkdir(self._full_path(path), mode)

    def statfs(self, path):
        full_path = self._full_path(path)
        stv = os.statvfs(full_path)
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    def unlink(self, path):
        return os.unlink(self._full_path(path))

    def symlink(self, name, target):
        return os.symlink(name, self._full_path(target))

    def rename(self, old, new):
        return os.rename(self._full_path(old), self._full_path(new))

    def link(self, target, name):
        return os.link(self._full_path(target), self._full_path(name))

    def utimens(self, path, times=None):
        return os.utime(self._full_path(path), times)

    # File methods
    # ============

    def open(self, path, flags):
        return 0
        full_path = self._full_path(path)
        return os.open(full_path, flags)

    def create(self, path, mode, fi=None):
        full_path = self._full_path(path)
        return os.open(full_path, os.O_WRONLY | os.O_CREAT, mode)

    def read(self, path, length, offset, fh):
        print("+ read(%s, %s, %s, %s)" % (path, length, offset, fh), file=sys.stderr)
        # os.lseek(fh, offset, os.SEEK_SET)
        # return os.read(fh, length)
        if offset < 2000:
            return b"Go get some coffee\n"
        return b""

    def write(self, path, buf, offset, fh):
        os.lseek(fh, offset, os.SEEK_SET)
        return os.write(fh, buf)

    def truncate(self, path, length, fh=None):
        full_path = self._full_path(path)
        with open(full_path, 'r+') as f:
            f.truncate(length)

    def flush(self, path, fh):
        return 0
        return os.fsync(fh)

    def release(self, path, fh):
        return 0
        return os.close(fh)

    def fsync(self, path, fdatasync, fh):
        return self.flush(path, fh)

    # We add one more key to xattr: 'user.owncloud.virtual'
    # * set the value to b'0' or b'' then the file is physical.
    # * set the value to b'1' or (discouraged: anything else), then the file is virtual.
    # * setting this on a directory affects the entire subtree, until a subdirectory
    #   has it set explicitly. All affected files receive a copy of this attribute value.
    #   Subdirectories don't.
    # * the value remains on a directory until the first file gets this value set differently.
    #   then the attribute is removed from the directory.
   
    def listxattr(self, path):
        full_path=self._full_path(path)
        xa = os.listxattr(path=full_path, follow_symlinks=True)
        if os.path.isfile(full_path) and "user.owncloud.virtual" not in xa:
            xa.append("user.owncloud.virtual")
        return xa

    def getxattr(self, path, name, position=0):
        full_path = self._full_path(path)
        print("getxattr "+str(self)+" path="+full_path+" name="+name)
        if os.path.isfile(full_path):
            if name == "user.owncloud.virtual":
                return b"maybe"
        return os.getxattr(full_path, name)

    def setxattr(self, path, name, value, options, position=0):
        full_path = self._full_path(path)
        print("getxattr "+str(self)+" path="+full_path+" name="+name+" value="+str(value)+" options="+str(options))
        if name == "user.owncloud.virtual":
            (uid, gid, pid) = fuse_get_context()	# CAUTION: Thread safe? be in self..., no?
            print("getxattr not impl. uid,gid,pid = ", uid, gid, pid)
            raise FuseOSError(errno.EREMOTE)        # not impl. actually :-)
        return os.setxattr(full_path, name, value, flags=options)


def main(mountpoint, root):
    FUSE(Passthrough(root), mountpoint, nothreads=True, foreground=True, debug=True)

if __name__ == '__main__':
    main(sys.argv[2], sys.argv[1])

