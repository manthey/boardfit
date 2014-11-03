#!/usr/bin/python

import copy
import itertools
import multiprocessing
import os
import pprint
import re
import signal
import struct
import sys
import time

try:
   import PIL.Image
except Exception:
   pass

Verbose = 0


def add_image(base, sub, x0, y0, fliph=False, flipv=False, maxval=0xFF):
   """Add a sub image to a base image.
   Enter: base: the base image in [y][x] format.  Modified.
          sub: the image to add in [y][x] format.
          x0, y0: position within the base image that the upper left of
                  the sub image will be located.  May be negative.
          flipx, flipv: flip the sub image along one of the axes.
          maxval: any value equal to or above this isn't coied."""
   bw = len(base[0])
   bh = len(base)
   sw = len(sub[0])
   sh = len(sub)
   swm1 = sw-1
   shm1 = sh-1
   for y in xrange(max(0, -y0), min(sh, bh-y0)):
      by = y+y0
      if flipv:
         line = sub[shm1-y]
      else:
         line = sub[y]
      baseline = base[by]
      if fliph:
         for x in xrange(max(0, -x0), min(sw, bw-x0)):
            p = line[swm1-x]
            if p>=maxval:
               continue
            bx = x+x0
            if p<baseline[bx]:
               baseline[bx] = p
      else:
         for x in xrange(max(0, -x0), min(sw, bw-x0)):
            p = line[x]
            if p>=maxval:
               continue
            bx = x+x0
            if p<baseline[bx]:
               baseline[bx] = p


def blank_image(w, h):
   """Create a blank image array of the [y][x] format of the specified
    size.
   Enter: w, h: dimensions of new image.
   Exit:  image: the new image."""
   image = []
   for line in xrange(h):
      image.append([0xFF]*w)
   return image


def get_state(current, best):
   """Format the current state of the image processing stack.
   Enter: current: the image processing stack, including the state.
          best: the current best data found.
   Exit:  state: the state string."""
   out = []
   for p in xrange(current['parts']):
      if p<len(current['state']):
         state = current['state'][p]
         out.append('%*d%c%c%*d,%*d '%(current['part_digits'], state['num'], '-H'[state['fliph']], '-V'[state['flipv']], current['x_digits'], state['x'], current['y_digits'], state['y']))
      else:
         out.append(' '*(4+current['part_digits']+current['x_digits']+current['y_digits']))
   out.append('%*d'%(current['x_digits'], current['w']))
   out.append('%*d'%(current['x_digits'], best['w']))
   if 'tasks_left' in best:
      out.append('%*d:%*d'%(best['task_digits'], best['task_watch'], best['task_digits'], best['tasks_left']))
   out = " ".join(out)
   return out


def load_file(parts, file, width, gap, verbose=0, lock=None, priority=None, num=None):
   """Load a file, generating a mask for it.
   Enter: parts: a list to store the result in.
          file: the path of the file to load.
          width: the width of the final board.
          gap: the width of the mask to add to each file.
          verbose: the verbosity for output.
          lock: a multiprocessing lock.
          priority: the priority for this process.
          num: the number to assign this file.  None for auto-numbering."""
   if priority:
      set_priority(priority)
   data = open(file, "rb").read()
   if not data.startswith('P5'):
      print "File %s is not a P5 PPM"%file
      sys.exit(0)
   groups = re.match('(P5\W([1-9][0-9]*)\W([1-9][0-9]*)\W([1-9][0-9]*).)', data).groups()
   w = int(groups[1])
   h = int(groups[2])
   data = data[len(groups[0]):]
   pixels = [struct.unpack('%dB'%w, data[w*i:w*(i+1)]) for i in xrange(h)]
   # Trim edges that are too light to care about
   while True:
      delete = True
      for i in xrange(len(pixels[0])):
         if pixels[0][i]<0xC0:
            delete = False
      if not delete:
         break
      pixels = pixels[1:]
   pixels = pixels[:width]
   while True:
      delete = True
      for i in xrange(len(pixels[-1])):
         if pixels[-1][i]<0xC0:
            delete = False
      if not delete:
         break
      pixels = pixels[:-1]
   while True:
      delete = True
      for i in xrange(len(pixels)):
         if pixels[i][0]<0xC0:
            delete = False
      if not delete:
         break
      pixels = [line[1:] for line in pixels]
   while True:
      delete = True
      for i in xrange(len(pixels)):
         if pixels[i][-1]<0xC0:
            delete = False
      if not delete:
         break
      pixels = [line[:-1] for line in pixels]
   part = {'w':len(pixels[0]), 'h':len(pixels), 'data':pixels, 'file':file}
   mask = blank_image(part['w']+gap*2, part['h']+gap*2)
   check = []
   for dy in xrange(-gap, gap+1):
      for dx in xrange(-gap, gap+1):
         if dx*dx+dy*dy<=(gap+0.5)*(gap+0.5):
            check.append((dx, dy))

   starttime = time.time()
   for (dx, dy) in check:
      if verbose>=2:
         if lock:
            lock.acquire();
         sys.stdout.write("%3d,%3d %s  \r"%(dx, dy, file))
         sys.stdout.flush()
         if lock:
            lock.release();
      add_image(mask, pixels, dx+gap, dy+gap, maxval=0xC0)

   part['mask'] = mask
   if verbose>=3:
      write_ppm(file+'.data.ppm', part['data'])
      write_ppm(file+'.mask.ppm', part['mask'])
   if lock:
      lock.acquire();
   if num is None:
      part['num'] = len(parts)
   else:
      part['num'] = num
   parts.append(part)
   if verbose>=1:
      print "%5.3fs to create mask for %d: %s (%d x %d)"%(time.time()-starttime, part['num'], file, part['w'], part['h'])
   if lock:
      lock.release();


def load_files(files, width, gap, verbose=0, multiprocess=False, priority=None):
   """Load a set of files, generating masks for each of them.
   Enter: files: a list of file names to load.
          width: the width of the final board.
          gap: the width of the mask to add to each file.
          verbose: the verbosity for output.
          multiprocess: if True or a positive number, use multiprocessing.  The
                        number can specify how many worker threads are used.
          priority: the priority to set if running in a multiprocess manner.
   Exit:  parts: the files loaded and processed."""
   parts = []
   if multiprocess:
      if multiprocess is not True:
         pool = multiprocessing.Pool(multiprocess, initializer=worker_init)
      else:
         pool = multiprocessing.Pool(initializer=worker_init)
      manager = multiprocessing.Manager()
      lock = manager.RLock()
      parts = manager.list(parts)
   else:
      pool = None
      lock = None

   try:
      num = 0
      for file in files:
         if pool:
            pool.apply_async(load_file, args=(parts, file, width, gap, verbose, lock, priority, num))
         else:
            load_file(parts, file, width, gap, verbose, num=num)
         num += 1
      if pool:
         pool.close()
         pool.join()
   except KeyboardInterrupt:
      if pool:
         try:
            pool.terminate()
            pool.join()
         except Exception:
            pass
      print '\nCancelled'
      sys.exit(1)
   return parts


def overlap_image(base, sub, x0, y0, fliph=False, flipv=False, maxval=0xC0):
   """Check if a sub image overlaps a base image.
   Enter: base: the base image in [y][x] format.  Modified.
          sub: the image to add in [y][x] format.
          x0, y0: position within the base image that the upper left of
                  the sub image will be located.  May be negative.
          flipx, flipv: flip the sub image along one of the axes.
          maxval: any value equal to or above this is ignored.
   Exit:  overlaps: True if the image overlaps, False if it doesn't"""
   bw = len(base[0])
   bh = len(base)
   sw = len(sub[0])
   sh = len(sub)
   swm1 = sw-1
   shm1 = sh-1
   for y in xrange(max(0, -y0), min(sh, bh-y0)):
      by = y+y0
      if flipv:
         line = sub[shm1-y]
      else:
         line = sub[y]
      baseline = base[by]
      if fliph:
         for x in xrange(max(0, -x0), min(sw, bw-x0)):
            p = line[swm1-x]
            if p>=maxval:
               continue
            bx = x+x0
            if baseline[bx]<maxval:
               return True
      else:
         for x in xrange(max(0, -x0), min(sw, bw-x0)):
            p = line[x]
            if p>=maxval:
               continue
            bx = x+x0
            if baseline[bx]<maxval:
               return True
   return False


def process_image(current, parts, partnum, best, lock=None):
   """Process an image.
   Enter: current: the current layout state.
          parts: the list of parts to process in order.
          partnum: the 0-based index into the parts to process.
          best: a dictionary with the best result so far; can be changed.
          lock: a multiprocessing lock."""
   if not 'data' in current:
      current['data'] = blank_image(best['w'], current['height'])
   if not 'orient' in current:
      if parts[partnum]['num']:
         orientrange = 4
      else:
         orientrange = 1
      for orient in xrange(orientrange):
         process_image_orient(current, parts, partnum, best, (orient&1)==1, (orient&2)==2, lock)
   else:
      orient = (current['orient']>>(2*current['orientnum'][parts[partnum]['num']]))&3
      process_image_orient(current, parts, partnum, best, (orient&1)==1, (orient&2)==2, lock)


def process_image_orient(current, parts, partnum, best, fliph, flipv, lock=None):
   """Process an image in a specific orientation.
      current contains lastx, lasty (the last location tried), maxw (the
    maximum length of used part of the plank including gap), w (the length
    of the used part of the plank), data (the [y][x] pixel values, state
    (the process state for status), and gap.
      parts is a list of parts, each of which contains data (the [y][x]
    pixel values), mask (the enlarged image), and num (the original
    0-based image number).
      best contains data (the [y][x] pixel values), w (the used part of
    the plank), and maxw (the maximum available plank).
   Enter: current: the current layout state.
          parts: the list of parts to process in order.
          partnum: the 0-based index into the parts to process.
          best: a dictionary with the best result so far; can be changed.
          fliph, flipv: the orientation of the image for processing.
          lock: a multiprocessing lock."""
   gap = current['gap']
   height = current['height']
   verbose = current['verbose']
   group_key = tuple([part['num'] for part in parts[partnum:]])
   group_w = current.get('widths', {}).get(group_key, None)
   part = parts[partnum]
   for x in xrange(current['lastx'], current['maxw']+1):
      if group_w and x+group_w>=best['w']:
         break
      if x+part['w']>=best['w']:
         break
      overlapped = False
      for y in xrange(0, height-parts[partnum]['h']+1):
         if best['w'] in current.get('widths_values', {}):
            return
         if overlap_image(current['data'], part['mask'], x-gap, y-gap, fliph, flipv):
            overlapped = True
            continue
         newcur = copy.deepcopy(current)
         add_image(newcur['data'], part['data'], x, y, fliph, flipv)
         newcur['lastx'] = x
         newcur['lasty'] = y
         newcur['maxw'] = max(newcur['maxw'], x+part['w']+gap)
         newcur['w'] = max(newcur['w'], x+part['w'])
         newcur['state'].append({'num':part['num'], 'fliph':fliph, 'flipv':flipv, 'x':x, 'y':y})
         if verbose>=5 or (((verbose>=1 and partnum+1==len(parts)) or verbose>=2) and (not 'task' in newcur or newcur['task']==best['task_watch'])):
            if verbose>=4 or time.time()-best.get('laststatus', 0)>=1:
               state = get_state(newcur, best)
               if lock:
                  lock.acquire();
               sys.stdout.write('%-79s\r'%state[-79:])
               sys.stdout.flush()
               if lock:
                  lock.release();
               curtime = time.time()
               best['laststatus'] = curtime
               if curtime-best.get('lastlogppm', 0)>60:
                  write_ppm('status.ppm', newcur['data'], best['w'], quiet=4, verbose=verbose)
                  if newcur.get('gif', False):
                     iptr = PIL.Image.open('status.ppm')
                     try:
                        os.unlink('status,gif')
                     except Exception:
                        pass
                     iptr.save('status.gif', format="GIF")
                     del iptr
                  best['lastlogppm'] = time.time()
         if newcur['w']>=best['w']:
            del newcur
            continue
         if partnum+1==len(parts):
            best['w'] = newcur['w']
            best['data'] = newcur['data']
            if verbose>=3 or (verbose>=1 and current['parts']==current['totalparts']):
               if lock:
                  lock.acquire();
               print get_state(newcur, best)
               print 'Current best width: %d '%best['w']
               if lock:
                  lock.release();
            if verbose>=3 or (verbose>=2 and current['parts']==current['totalparts']):
               write_ppm('current'+current['out'], best['data'], best['w'], verbose=verbose)
         else:
            process_image(newcur, parts, partnum+1, best, lock=lock)
         del newcur
      # This optimization is only correct if the parts are individually
      # contiguous
      if not overlapped:
         break


def process_image_task(current, parts, partnum, best, lock=None):
   """Process an image, marking the task started and finished as
    appropriate.
   Enter: current: the current layout state.
          parts: the list of parts to process in order.
          partnum: the 0-based index into the parts to process.
          best: a dictionary with the best result so far; can be changed.
          lock: a multiprocessing lock."""
   best['tasks_started'] += '%d '%current['task']
   if current['priority']:
      set_priority(current['priority'])
   process_image(current, parts, partnum, best, lock)
   best['tasks_finished'] += '%d '%current['task']


def process_parts(Parts, Current, Best):
   """Calculate the best fit for a set of parts.
   Enter: Parts: an array of parts to calculate.
          Current: the current settings to use in the calculation.
          Best: a dictionary to store the result.
   Exit:  bestwidth: the best calculated board size."""
   Gap = Current['gap']
   Beat = Current['beat']
   Height = Current['height']
   Multiprocess = Current['multiprocess']
   OrientFirst = Current['orientfirst']
   Verbose = Current['verbose']

   maxw = sum([part['w']+Gap for part in Parts])
   if Current['widths']:
      for perm in itertools.permutations(Parts):
         key = tuple([part['num'] for part in perm[1:]])
         if key in Current['widths']:
            maxw = min(maxw, perm[0]['w']+Current['widths'][key]+Gap*2)
   if Verbose>=3:
      print 'maxw', tuple([part['num'] for part in Parts]), maxw

   imgw = maxw
   if Beat and Beat<imgw:
      imgw = Beat
   Best.clear()
   Best.update({'w': imgw, 'maxw': maxw, 'data': blank_image(imgw, Height)})
   Current.update({'lastx': 0, 'lasty': 0, 'maxw': 0, 'w': 0, 'state':[], 'parts': len(Parts)})
   Current['part_digits'] = len('%d'%len(Parts))
   Current['x_digits'] = len('%d'%imgw)
   Current['y_digits'] = len('%d'%Height)

   if Multiprocess:
      if Multiprocess is not True:
         pool = multiprocessing.Pool(Multiprocess, initializer=worker_init)
      else:
         pool = multiprocessing.Pool(initializer=worker_init)
      manager = multiprocessing.Manager()
      tasks = []
      origBest = Best
      Best = manager.dict(origBest)
      lock = manager.RLock()
      Best['tasks_left'] = 0
      Best['tasks_started'] = ""
      Best['tasks_finished'] = ""
      tasks_last_list = ""
      tasks_started = {}
      tasks_finished = {}
      Best['task_watch'] = 0
      Best['task_digits'] = 1
   else:
      pool = None
      lock = None

   try:
      if OrientFirst:
         Current['orientnum'] = {}
         for opn in xrange(len(Parts)):
            Current['orientnum'][Parts[opn]['num']] = opn
         for orient in xrange(0, 4**len(Parts), 4):
            for combo in itertools.permutations(Parts):
               current = copy.deepcopy(Current)
               current['orient'] = orient
               if pool:
                  current['task'] = len(tasks)
                  tasks.append(pool.apply_async(process_image_task, args=(current, combo, 0, Best, lock)))
                  Best['tasks_left'] = len(tasks)
                  Best['task_digits'] = len('%d'%len(tasks))
               else:
                  process_image(current, combo, 0, Best)
               del current
      else:
         for combo in itertools.permutations(Parts):
            if pool:
               current = copy.deepcopy(Current)
               current['task'] = len(tasks)
               tasks.append(pool.apply_async(process_image_task, args=(current, combo, 0, Best, lock)))
               del current
               Best['tasks_left'] = len(tasks)
               Best['task_digits'] = len('%d'%len(tasks))
            else:
               process_image(Current, combo, 0, Best)
      if pool:
         pool.close()
         while len(tasks):
            try:
               tasks[0].get(timeout=1)
            except Exception:
               pass
            for t in xrange(len(tasks)-1, -1, -1):
               if tasks[t].ready():
                  tasks[t].get()
                  tasks[t:t+1] = []
            Best['tasks_left'] = len(tasks)
            try:
               if tasks_last_list != Best['tasks_started']+Best['tasks_finished']:
                  tasks_last_list = Best['tasks_started']+Best['tasks_finished']
                  tasks_started = dict.fromkeys([int(task) for task in Best['tasks_started'].strip().split()])
                  tasks_finished = dict.fromkeys([int(task) for task in Best['tasks_finished'].strip().split()])
                  watch = min([task for task in tasks_started.keys() if not task in tasks_finished])
                  if Best['task_watch'] != watch:
                     Best['task_watch'] = watch
            except Exception:
               pass
         pool.join()
         origBest.update(Best)
         Best = origBest
   except KeyboardInterrupt:
      if pool:
         try:
            pool.terminate()
            pool.join()
         except Exception:
            pass
      print '\nCancelled'
      sys.exit(1)
   return Best['w']


def set_priority(priority):
   """Set the program priority.
   Enter: priority: the priority to set.  Can be 'low', 'normal', 'idle',
                    or a nice-like number."""
   try:
      import psutil
   except Exception:
      return
   try:
      nice = int(priority)
   except:
      nice = None
   if sys.platform=='win32':
      if priority=='idle' or (nice is not None and nice>10):
         level = psutil.IDLE_PRIORITY_CLASS
      elif priority=='low' or (nice is not None and nice>0):
         level = psutil.BELOW_NORMAL_PRIORITY_CLASS
      elif priority=='normal' or (nice is not None and nice==0):
         level = psutil.NORMAL_PRIORITY_CLASS
      else:
         level = psutil.NORMAL_PRIORITY_CLASS
   else:
      if nice is not None:
         level = nice
      elif priority=='idle':
         level = 19
      elif priority=='low':
         level = 10
      else:
         level = 0
   proc = psutil.Process(os.getpid())
   proc.nice(level)


def worker_init():
   """Supress the ctrl-c signal in the worker processes."""
   signal.signal(signal.SIGINT, signal.SIG_IGN)


def write_ppm(filename, data, maxw=None, quiet=1, verbose=None):
   """Write a ppm from the pixels in a array of arrays.
   Enter: filename: name to write to.
          data: array of [y][x] pixels.
          maxw: if specified, only write out the left side of the image,
                truncated at this width.
          quiet: only print that a file was output if the verbosity is
                 higher than this value."""
   if verbose is None:
      verbose = Verbose
   w = len(data[0])
   if maxw and maxw<w:
      w = maxw
   if verbose>=quiet:
      print "Saved %s (%d x %d)"%(filename, w, len(data))
   fptr = open(filename, "wb")
   fptr.write('P5 %d %d 255\n'%(w, len(data)))
   for line in data:
      fptr.write(struct.pack('%dB'%w, *line[:w]))
   fptr.close()


if __name__=='__main__':
   starttime = time.time()
   Help = False
   Files = []
   Height = int(11.5*25)
   Gap = int(0.5*25)
   OrientFirst = False
   Beat = None
   Multiprocess = False
   GenerateGIF = False
   OutFile = 'best.ppm'
   Priority = None
   for arg in sys.argv[1:]:
      if arg.startswith('--beat='):
         Beat = int(arg.split('=', 1)[1])
      elif arg.startswith('--gap='):
         Gap = int(arg.split('=', 1)[1])
      elif arg=="--gif":
         GenerateGIF = True
      elif arg.startswith('--height='):
         Height = int(arg.split('=', 1)[1])
      elif arg=="--multi":
         Multiprocess = True
      elif arg.startswith("--multi="):
         Multiprocess = int(arg.split("=", 1)[1])
         if Multiprocess<=1:
            Multiprocess = False
      elif arg=="--orient":
         OrientFirst = True
      elif arg.startswith('--out='):
         OutFile = arg.split('=', 1)[1]
      elif arg.startswith("--priority="):
         Priority = arg.split('=', 1)[1]
      elif arg=="-v":
         Verbose += 1
      elif arg.startswith('-'):
         Help = True
      else:
         Files.append(arg)
   if Help or not len(Files):
      print """Compute best-fit lumber usage.

Syntax: boardfit.py (ppm files ...) --height=(height of board) --gap=(gap size)
                    --orient --beat=(length) --multi[=(workers)] --gif
                    --out=(output ppm) --priority=(priority) -v

The input files must be P5 ppm files with the top edge considered
non-croppable.  The bottom edge may be cropped on narrow boards.  In these
files, black represents used area and white unused.  If a pixel is lighter than
or equal to 0xC0, it is ignored for overlap calculations.
--beat ignores solutions that are longer than the specified length.
--gap is the space to leave between parts.
--gif generates status gifs (in addition to status ppms).
--height is the height of the board in the same units as the input files.
--multi uses multiprocessing to take advantage of multiple cores.  If no number
  is specified, one worker per core is started.  A value of 0 or 1 disables
  multiprocessing.
--orient tries all of one set of orientations before trying the next one.
  Otherwise, each part is tried in all orientations before changing anything
  about the next one.  Using --orient can result in greater parallelization in
  multiprocessing, but will have slightly more overhead.
--out specifies the name of the output ppm.  An additional file current(out) is
  written whenever a local best is obtained.
--priority asks the program to run at a particular priority level.  Options are
  'normal', 'low', 'idle', or a nice-like number.
-v increases the verbosity."""
      sys.exit(0)

   if Priority and not Multiprocess:
      set_priority(Priority)

   Parts = load_files(Files, Height, Gap, Verbose, Multiprocess, Priority)

   Current = {'gap': Gap, 'height': Height, 'verbose': Verbose, 'gif': GenerateGIF, 'out': OutFile, 'multiprocess': Multiprocess, 'beat': Beat, 'orientfirst': OrientFirst, 'priority': Priority, 'totalparts': len(Parts)}
   Best = {}

   Current['widths'] = {}
   for part in Parts:
      Current['widths'][(part['num'], )] = part['w']
   Current['widths_values'] = dict.fromkeys(Current['widths'].values())
   for comblen in xrange(2, len(Parts)):
      for combo in itertools.combinations(Parts, comblen):
         w = process_parts(combo, Current, {})
         if Verbose>=2:
            out = 'Partial: %s %d'%(str(tuple([part['num'] for part in combo])), w)
            print "%-79s"%out
         keys = [part['num'] for part in combo]
         for perm in itertools.permutations(keys):
            Current['widths'][perm] = w
      if Verbose>=3:
         pprint.pprint(Current['widths'])
      Current['widths_values'] = dict.fromkeys(Current['widths'].values())

   process_parts(Parts, Current, Best)

   write_ppm(Current['out'], Best['data'], Best['w'])
   print 'Best width: %d (%3.1fs)'%(Best['w'], time.time()-starttime)

