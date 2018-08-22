# ocffs - A friendly Fuse Filesystem for ownCloud

Wait, did they say 'virtual files' or 'virtual file system'?

Guess what this does:

    setfattr -n user.owncloud.virtual -v 1 Photos/Paris.jpg
    setfattr -n user.owncloud.virtual -v 0 Photos/Paris.jpg

## Background

With desktop client version 2.5.0 a new feature is presented: Virtual files.
This feature can be thought of an enhancement on the selective folder sync, but
this time on a per file basis, and you now always see all folders and files in
your local file system (unless you also use selective folder sync at the same
time, then disabled folders are gone).

Files can be now in one of two states, virtual or physical. If an Example.PDF
file is virtual, an extra suffix is added. It is named
Example.PDF.owncloud (or Example.PDF.*_virtual for branded clients). Per rename
of file browser shell integration you can trigger a download, and the
placeholder is removed as soon as the pyhsical file is ready.

Per default all files are virtual, that means the initial sync from server to desktop is blazing fast.

## Motivation

As of 2.5.0 the virtual files feature is not yet a filesystem, although ist is
already marketed as such in the press. Experimental they say. OCFFS uses the
current implementation as a basis and adds a real virtual file system on top.

The current implementation has a number of limitaitons, that for sure will 
irritate users and confuse application programs.

* Placeholder files have a different name, due to the added extension.
  This means that mimetypes and icons are not right, and all files are associated
  with the 'owncloud' appliction, when double clicked in the GUI.
* Placeholder files have the wrong size. One byte.
  Reading from or writing to a placeholder is menaingless. Don't do it.
* Placeholder files may have other attributes wrong, like permissions and timestamps.
* Mechanisms to switch between the two states (virtual and physical) are cumbersome.
  
A virtual file system could improve a lot here:

* Names are always correct. Icons, mimetypes and linked applications are correct.
* Size, timestamps, permissions and everything are correct.
* Opening a file while virtual triggers would work as expected, just slower.
  It triggers a download, and once finished, the file is physical and subsequent reads are fast.
* Applications that store a recently used list, are no longer confused, when the files become virtual.
* Give users more flexible tools to switch between virtual and pyhsical and monitor state.
* Permanent virtual state, even after access.

The prototype defines new filesystem semantics as a suggestion for wider adoption (WIN and OSX clients).
It gives early adopters the prossibilty to evaluate. Feedback welcome.

## Availability

OCFFS is an add on that can be started ontop of any sync folder connection, where the virtual files feature is enabled. To enable, have this in the client config file:

    [General]
    showExperimentalOptions=true

OCFFS is based on FUSE, a user land filesystem abstraction available in Linux (and OSX, though untested there).
For the Windows Desktop the Dokan project provides a FUSE-compatible API (also untested).
The first prototype requires python3 and interacts with the client. Implementations for speed would be built into the desktop client (using C or C++ then).

The first draft is available at https://github.com/jnweiger/OCFFS - please file issues there.

## Implementation details

These are currently Linux only considerations. OSX and WIN clients may choose
different ways to implement the same semantics. 

The ownCloud client already presents its files in the local filesystem. OCFFS
takes that 'lower level view' and represents the same contents as a nicer tree
of files and folders.  The first prototype uses a second mount point elsewhere
to create that presentation. Which means, the user sees all files twice, --
that is not good, creating the mountpoint inplace is preferable. We need to
investigate if that is prossible with the current 'add-on' architecture. It is
definitly the way to go when built into the client. 

Applications or shell programs that are running before the client was started,
already see the raw lower level view. Weather mounting the friendly view ontop
or elsewhere, we need to handle the case that a Linux process has its current
working directory in the original sync folder, and does not immediately "see"
what is mounted ontop (or elsewhere). When OCFFS starts, it should use the
/proc/ filesystem to find such process, and e.g. report them via desktop
notifications.

The owncloud client itself may or may not have its current working directory
inside the sync folder. In any case, this process must always operate on the
original raw view. Same for a debugging shell. OCFFS detects the pid of the
client on startup and enters pure passthrough mode for all filesystem requests
coming from the client. Same can be configured for processes with a special
effective UID (e.g. euid=0) for debugging.

The client uses inotify in the entire sync folder tree. Being a FUSE file
system, OCFFS also gets all events its mountpoint, but not necessarily on the
lower level view. Mounting inplace may or may not interfere with the inotify
events the client expects to see. To be evaluated.

python-fusepy is an efficient, thin and apparently complete binding on libfuse. 
It is yet unknown if the self object allows to access 
the needed PID and UID informations. Switch libfuse to raw_fi mode?
class fuse_ctx has uid, gid, pid. Also class fuse_context, method fuse_get_context().

Need to access the sqlite database of the client, for the set of "correct" metadata.
Sqlite has a global lock. That should do for the prototype code.

Issue: Are we single threaded? Can we handle other filesystem calls, while we 
block a read()?
Issue: only the mounting user can see the files. All other users get an invalid stat.

There is also the reference implementation of libfuse, which also has python(3?) bindings.

