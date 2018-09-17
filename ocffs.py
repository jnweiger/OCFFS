#! /usr/bin/env python3
#
# ocffs -- a friendly filesystem for ownCloud
#
# (C) 2018 jw@owncloud.com
# Distribute under GPLv2 or ask
#
# Usage:
# ocffs.py syncfolder [otherfolder]
#
# 2018-08-19, jw 0.1 -- initial draft.
# 2018-08-20, jw 0.2 -- xattr can be used. readdir() no longer sees placeholders.
# 2018-08-21, jw 0.3 -- _oc_stat() done. all placeholders properly hidden.
# 2018-08-22, jw 0.4 -- switching virtial physical via xattr user.owncloud.virtual works!
#
# TODO: read/write


from __future__ import with_statement, print_function

import os, re, sys
import psutil, errno, sqlite3, time, socket

# from fuse import FUSE, FuseOSError, Operations
from fusepy import FUSE, FuseOSError, Operations, fuse_get_context

_version_ = '0.4'

class OCFFS(Operations):
    """
    OCFFS -- a friendly filesystem layer for ownCloud.

    This is a mostly "transparent" pass-through layer implemented with FUSE.
    All files and directories as maintained by the owncloud desktop client
    are exposed in the mountpoint as they are. The important exception are
    *.owncloud and *.*_virtual placeholder files. They are presented as real
    files.
    """

    def __init__(self, root, mountpoint=None):
        self.root = root
        self.mountpoint = mountpoint
        self.vfd = {}           # virtual file descriptor table.
        self.blocksize = 4096   # our read will return blocks of this size.
        # find the owncloud db file:
        self.dbfile = None
        for dbfile in os.listdir(root):
            if re.match('\._sync_[a-f0-9]+\.db$', dbfile): self.dbfile = root + '/' + dbfile
        if self.dbfile is None:
            print("No database file '._sync_*.db' found in "+root, file=sys.stderr)
            sys.exit(1)

        pids = self._find_owncloud_threads()
        if len(pids) < 1:
            print("dbfile '"+self.dbfile+"' has no owncloud client process.", file=sys.stderr)
            print("Please start the client or remove the orphant dbfile", file=sys.stderr)
            sys.exit(1)
        self.client_executable_shortname = pids[0][1]
        self.client_pid = pids[0][0]
        self.client_uid = pids[0][2]
        if self.client_executable_shortname == "owncloud":
            self.virtual_suffix = "."+self.client_executable_shortname
        else:
            self.virtual_suffix = "."+self.client_executable_shortname+"_virtual"
        print("ownCloud client found: pid=%s name=%s" % (pids[0][0], pids[0][1]), file=sys.stderr)
        print("ownCloud db file found: %s" % self.dbfile, file=sys.stderr)

        if len(pids) > 1:
            print("Extra processes on dbfile ignored: "+str(pids), file=sys.stderr)
        if self.dbfile:
            self.db = sqlite3.connect(self.dbfile)

    def __enter__(self):
        print("OCFFS v%s starting ..." % (_version_), file=sys.stderr)
        return self

    def __exit__(self, type, value, traceback):         # better than __del__ but requires a with in main below.
        print("\nOCFFS exiting...", file=sys.stderr)
        if self.db:
            self.db.close()


    # Helpers
    # =======

    def _oc_path(self, partial, virt=None):
        """
        This adds the sync folder prefix to the partial path, and
        also translates between virtual and physical path names.
        The optional parameter virt controls this:
        virt=True     assert the name is virtual, regardless what is in the filesystem.
        virt=False    assert the name is physical, regardless what is in the filesystem.
        virt=None     look into the filesystem, see which one exist, then use that one.

        Returns the tuple (path,True) if it is virtual (and the suffix is asserted in path).
        or the tuple (path,False) if it is physical.
        When called with virt=None, it may return (path,None) if neither exists.
        """
        partial = partial.lstrip("/")
        path = os.path.join(self.root, partial)
        if path.endswith(self.virtual_suffix):  # always accept both physical and virtual name.
            vpath = path
            rpath = path[:-len(self.virtual_suffix)]
        else:
            rpath = path
            vpath = path + self.virtual_suffix
        if virt is None:
            if os.path.exists(rpath): return (rpath,False)
            if os.path.exists(vpath): return (vpath,True)
            return (rpath,None)
        if virt is False:
            return (rpath,False)
        return (vpath,True)


    def _find_owncloud_threads(self):
        """ enumerate processes, filter those with same euid as the dbfile.
            then find one that also has the dbfile open.
            We asume, we run as the user who owns the dbfile.
            (If not Process.open_file() may fail.)

            Returns a list of triples: [ (pid, name, uid), ... ]
        """
        db_path = os.path.realpath(self.dbfile)
        db_uid = os.stat(db_path).st_uid
        pids = []
        for p in psutil.process_iter(attrs=['name']):
            euid = p.uids().effective
            uid = p.uids().real
            if db_uid == euid or db_uid == uid:
                # print("+ pid=%s (%s) match db_uid=%s euid=%s uid=%s" % (p.pid, p.name(), db_uid,euid,uid), file=sys.stderr)
                try:
                    for f in p.open_files():
                        if f.path == db_path:
                            if p.pid == os.getpid():
                                print("+ FIXME: saw myself on the database. Harmless, but should not happen.", file=sys.stderr)
                                pass
                            else:
                                # print("+ seen: owncloud client pid=%s name=%s" % (p.pid, p.name()), file=sys.stderr)
                                pids.append([p.pid, p.name(), db_uid])
                except:
                    # open_files may fire PermissionError or psutil._exceptions.AccessDenied
                    # on e.g. "gpg-agent", which does not like to be examined.
                    pass
        return pids


    def _oc_stat(self, path):
        """
        return stats as known by the owncloud client.
        Using the local sqlite file as "API" to the client.
        """
        (id, mtime, size, type) = ("--none--", -1, -1, -1)
        rpath = os.path.relpath(path, os.path.realpath(self.root))
        if rpath[:3] == '../':
            print("+ _oc_stat: path=%s is outside root=%s" % (path, os.path.realpath(self.root)), file=sys.stderr)
            return(id, mtime, size, type)

        cur = self.db.cursor()
        cur.execute('SELECT fileid,modtime,filesize,type FROM metadata WHERE path = ?', (rpath,))
        try:
            (id, mtime, size, type) = cur.fetchone()
        except:
            print("+ _oc_stat: SELECT failed: FROM metadata WHERE path="+rpath, file=sys.stderr)
            pass
        cur.close()	# invalidates cur.
        # print("+ _oc_stat: id=%s, mtime=%s, size=%s, type=%s" % (id, mtime, size, type), file=sys.stderr)
        return(id, mtime, size, type)


    def _be_transparent(self):
        """ check if we should switch in transparent mode. E.g. when
            owncloud client itself comes here, or when root user comes here.
            Returns True or False.
        """
        if os.getuid() == 0: return True
        (uid, gid, pid) = fuse_get_context()	# CAUTION: Thread safe? be in self..., no?
        if pid == self.client_pid: return True
        return False


    def _convert_p2v(self, path):
        """ trigger conversion from physical to virtual

            method: rename.
            (socket api: method not available)
        """
        rpath = path
        if rpath.endswith(self.virtual_suffix):
            print("+ _convert_p2v: is already virtual: path="+rpath, file=sys.stderr)
            return 0
        if os.path.isdir(rpath):
            print("+ _convert_p2v: not implemented on a directory. path="+rpath, file=sys.stderr)
            return 0
        print("+ _convert_p2v: rename '%s' to '%s'" % (rpath, rpath+self.virtual_suffix), file=sys.stderr)
        os.rename(rpath, rpath+self.virtual_suffix);
        return 1


    def _convert_v2p(self, path):
        """ trigger conversion from virtual to physical

            method: socket API.
            (rename also works, but has a self conflict as of 2.5.0~beta2)
        """
        # cmd="DOWNLOAD_VIRTUAL_FILE:/home/testy/testpilotcloud2/ownCloud Manual.pdf.testpilotcloud_virtual"
        # echo "$cmd" | socat - UNIX-CONNECT:/run/user/1000/testpilotcloud/socket
        rpath = path
        if not rpath.endswith(self.virtual_suffix):
            print("+ _convert_v2p: is already physical: path="+rpath, file=sys.stderr)
            return 0
        sock_file = '/run/user/'+str(self.client_uid)+'/'+self.client_executable_shortname+'/socket'
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        cmd = "DOWNLOAD_VIRTUAL_FILE:"+os.path.realpath(rpath)+"\n"
        try:
            sock.connect(sock_file)
            sock.send(cmd.encode('utf-8'))
        except Exception as e:
            print("+ _convert_v2p: send failed: " + str(e), file=sys.stderr)
        sock.settimeout(0.2)
        seen = sock.recv(1024)
        seen = seen[:seen.rfind(b'\n')].decode('utf-8').split('\n')
        print("+ _convert_v2p: received: " + str(seen), file=sys.stderr)
        sock.close()
        return 1


    # Filesystem methods
    # ==================

    def access(self, path, mode):
        rpath,virt = self._oc_path(path)
        if not os.access(rpath, mode):
            raise FuseOSError(errno.EACCES)

    def chmod(self, path, mode):
        rpath,virt = self._oc_path(path)
        return os.chmod(rpath, mode)

    def chown(self, path, uid, gid):
        rpath,virt = self._oc_path(path)
        return os.chown(rpath, uid, gid)

    def getattr(self, path, fh=None):
        rpath,virt = self._oc_path(path)
        st = os.lstat(rpath)
        ret = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
                     'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))
        if virt and not self._be_transparent():
            (id, mtime, size, type) = self._oc_stat(rpath)
            ret['st_size'] = int(size)
            ret['st_mtime'] = int(mtime)
        print("+ getattr(%s, %s) returns %s" % (rpath, fh, str(ret)), file=sys.stderr)
        return ret

    def readdir(self, path, fh):
        rpath,virt = self._oc_path(path)
        transp = self._be_transparent()

        dirents = ['.', '..']
        if os.path.isdir(rpath):
            dirents.extend(os.listdir(rpath))
        for r in dirents:
            if not transp and r.endswith(self.virtual_suffix):
                r = r[:-len(self.virtual_suffix)]
            yield r

    def readlink(self, path):
        rpath,virt = self._oc_path(path)
        if virt:
            print("+ readlink virtual files cannot work.", file=sys.stderr)
            raise FuseOSError(errno.EREMOTE)
        return os.readlink(rpath, rpath)

    def mknod(self, path, mode, dev):
        rpath = self._oc_path(path, virt=False)[0]
        return os.mknod(rpath, mode, dev)

    def rmdir(self, path):
        rpath = self._oc_path(path, virt=False)[0]
        return os.rmdir(rpath)

    def mkdir(self, path, mode):
        rpath = self._oc_path(path, virt=False)[0]
        return os.mkdir(rpath, mode)

    def statfs(self, path):
        """
        CAUTION: what we return here as bsize, is the
        minimum block size that we have to return with read.
        """
        rpath = self._oc_path(path)[0]
        stv = os.statvfs(rpath)
        ret = dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))
        ret['f_bsize'] = self.blocksize
        return ret

    def unlink(self, path):
        return os.unlink(self._oc_path(path)[0])

    def symlink(self, name, target):
        rpath,virt = self._oc_path(name, virt=False)
        return os.symlink(name, self._oc_path(target)[0])

    def rename(self, old, new):
        rpath,virt = self._oc_path(old)
        if virt:
            print("+ rename virtual files is not supported by owncloud client.", file=sys.stderr)
            raise FuseOSError(errno.EREMOTE)
        return os.rename(rpath, self._oc_path(new, virt=False)[0])

    def link(self, target, name):
        # hard target is always physical, to start with.
        # WARN: the link is likely to break into a copy as soon as the client is syncing...
        rpath,virt = self._oc_path(name)
        if virt:
            print("+ hard link virtual files cannot work.", file=sys.stderr)
            raise FuseOSError(errno.EREMOTE)
        return os.link(self._oc_path(target,virt=False)[0], rpath)

    def utimens(self, path, times=None):
        return os.utime(self._oc_path(path)[0], times)

    # File methods
    # ============

    def open(self, path, flags):
        """
        filedescriptors are real, when we hit a physical file.
        filedescriptors are dummies (/dev/null), for virtual files.

        We keep record of our virtual filde descriptors in the vfd table.
        E.g.
        - flush() must be mocked away,
        - release() must know what to do...
        - store the flags to be checked in read() / write() calls.
        """
        rpath,virt = self._oc_path(path)
        fd = os.open("/dev/null", os.O_RDONLY)
        self.vfd[fd] = { 'rpath': rpath, 'flags': flags }
        print("+ open(%s, %s) returns %s" % (rpath,  flags, fd), file=sys.stderr)
        return fd       # a dummy file descriptor. But uniq. Perfect for indexing into vfd[].

    def create(self, path, mode, fi=None):
        rpath = self._oc_path(path, virt=False)[0]
        return os.open(rpath, os.O_WRONLY | os.O_CREAT, mode)

    def read(self, path, length, offset, fh):
        """
        CAUTION: This read has different semantics than the read system call.

        Read gets called with length as a multiple of our self.blocksize,
        assuming that our statfs() was called, to inform the kernel.

        If read returns less than one blocksize, the same read is retried once, then
        the kernel assumes that this is the end of the file and calls flush and release.

        The kernel advance offset only, if multiples of blocksize are returned by read.
        We are a filesystem, where the world is defined in blocks, not bytes.
        """
        print("+ read(%s, %s, %s, %s)" % (path, length, offset, fh), file=sys.stderr)
        if fh in self.vfd:
            if offset < 100:
                return b"go get some coffee\n"
            return b''
        else:
            os.lseek(fh, offset, os.SEEK_SET)
            return os.read(fh, length)

    def write(self, path, buf, offset, fh):
        print("+ write(%s, '%s', %s, %s, %s)" % (path, buf, offset, fh), file=sys.stderr)
        if fh in self.vfd:
            raise FuseOSError(errno.EREMOTE)    # virtual files just cannot be written for now.
        else:
            os.lseek(fh, offset, os.SEEK_SET)
            return os.write(fh, buf)

    def truncate(self, path, length, fh=None):
        rpath = self._oc_path(path)[0]
        with open(rpath, 'r+') as f:
            f.truncate(length)

    def fsync(self, path, fdatasync, fh):
        print("+ fsync(%s, %s, %s) delegates to flush()" % (path, fdatasync, fh), file=sys.stderr)
        return self.flush(path, fh)

    def flush(self, path, fh):
        print("+ flush(%s, %s)" % (path, fh), file=sys.stderr)
        if fh in self.vfd:
            return 0
        return os.fsync(fh)

    def release(self, path, fh):
        print("+ release(%s, %s)" % (path, fh), file=sys.stderr)
        if fh in self.vfd:
            print("+  del %s" % (str(self.vfd[fh])), file=sys.stderr)
            del self.vfd[fh]
            return os.close(fh)
        return os.close(fh)

    # We add one more key to xattr: 'user.owncloud.virtual'
    # * set the value to b'0' or b'' then the file is physical.
    # * set the value to b'1' or (discouraged: anything else), then the file is virtual.
    # * setting this on a directory affects the entire subtree, until a subdirectory
    #   has it set explicitly. All affected files receive a copy of this attribute value.
    #   Subdirectories don't.
    # * the value remains on a directory until the first file gets this value set differently.
    #   then the attribute is removed from the directory.

    def listxattr(self, path):
        rpath = self._oc_path(path)[0]
        xa = os.listxattr(path=rpath, follow_symlinks=True)
        if os.path.isfile(rpath) and "user.owncloud.virtual" not in xa:
            xa.append("user.owncloud.virtual")
        return xa

    def getxattr(self, path, name, position=0):
        rpath,virt = self._oc_path(path)
        print("+ getxattr(%s, %s, %s)" % (rpath, name, position), file=sys.stderr)
        if os.path.isfile(rpath):
            if name == "user.owncloud.virtual":
                if virt:
                    return b"1"
                else:
                    return b"0"
        return os.getxattr(rpath, name)

    def setxattr(self, path, name, value, options, position=0):
        rpath,virt = self._oc_path(path)
        if name == "user.owncloud.virtual" and not self._be_transparent():
            if value == b'0' or value == b'':
                if virt:
                    self._convert_v2p(rpath)
                else:
                    print("+ setxattr nothing to do. path is already physical: "+rpath, file=sys.stderr)
            else:
                if virt:
                    print("+ setxattr nothing to do. path is already virtual: "+rpath, file=sys.stderr)
                else:
                    self._convert_p2v(rpath)
            return 0
        return os.setxattr(rpath, name, value, flags=options)


## need user_allow_other in /etc/fuse.conf
def main(root, mountpoint=None):
    if mountpoint is None:
        mountpoint = root + ".ocffs"

    with OCFFS(root, mountpoint) as ocffs:
        try:
            FUSE(ocffs, mountpoint, nothreads=True, foreground=True, debug=True, allow_other=True)
        except RuntimeError:
            print(" -- mountpoint %s is only usable for current user." % mountpoint, file=sys.stderr)
            FUSE(ocffs, mountpoint, nothreads=True, foreground=True, debug=True, allow_other=False)

if __name__ == '__main__':
    if len(sys.argv) < 3:
      print("Usage: %s OC_SHAREFOLDER NEW_MOUNTPOINT" % (sys.argv[0]))
      sys.exit(1)
    main(sys.argv[1], sys.argv[2])

