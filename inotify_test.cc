// FROM https://sourceforge.net/p/fuse/mailman/message/24625009/
#include <iostream>
#include <sys/inotify.h>
#include <stdio.h>
#include <assert.h>
#include <unistd.h>	// read()

using namespace std;

int main(int argc, char **argv) 
{
  int inotify_fd = inotify_init();
  inotify_add_watch(inotify_fd, argv[1], IN_CLOSE_WRITE);
  int buf_size = sizeof(struct inotify_event) + FILENAME_MAX;

  struct inotify_event *event = (struct inotify_event *)malloc(buf_size);
  // Now wait for receiving an event on the inotify descriptor. 
  // You'll get an event if any file inside /path/to/some/directory is opened for writing and then closed.

  int read_ret = read(inotify_fd, event, buf_size);
  // Do the usual checks for errors on read_ret.
  if (read_ret < 0) 
  {
    cout << "read_ret < 0";
  }
  assert(read_ret == sizeof(struct inotify_event) + event->len);
  cout << "Got inotify event on file " << event->name << endl;

  return 0;
}
