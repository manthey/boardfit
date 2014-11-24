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

TasksLeft = None
TaskWatch = None
TaskDigits = None
TaskBestW = None

def add_image(base, sub, x0, y0, fliph=False, flipv=False, maxval=0xFF):
   """Add a sub image to a base image.
   Enter: base: the base image in [y][x] format.  Modified.
          sub: the image to add in [y][x] format.
          x0, y0: position within the base image that the upper left of
                  the sub image will be located.  May be negative.
          flipx, flipv: flip the sub image along one of the axes.
          maxval: any value equal to or above this isn't copied."""
   bw = len(base[0])
   bh = len(base)
   sw = len(sub[0])
   sh = len(sub)
   swm1 = sw-1
   shm1 = sh-1
   x1, x2 = max(0, -x0), min(sw, bw-x0)
   for y in xrange(max(0, -y0), min(sh, bh-y0)):
      if flipv:
         line = sub[shm1-y]
      else:
         line = sub[y]
      baseline = base[y+y0]
      if fliph:
         for x in xrange(x1, x2):
            p = line[swm1-x]
            if p>=maxval:
               continue
            bx = x+x0
            if p<baseline[bx]:
               baseline[bx] = p
      else:
         for x in xrange(x1, x2):
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


def calculate_ranges(image, maxw=None):
   """Calculate the left-most and right-most used pixel in each line of an
   image.
   Enter: image: an array of pixels in the [y][x] format.
          maxw: the maximum distaince to check.  None for all.
   Exit:  ranges: a list of tuples, one per line (y) in the image.  Each
                  tuple has the leftmost used pixel and the rightmost used
                  pixel.  If no pixels are used in that line, this is
                  stored as (None, None)"""
   ranges = []
   if maxw is None or maxw>len(image[0]):
      maxw = len(image[0])
   for line in image:
      minx = maxx = None
      minx = next((x for x in xrange(maxw) if line[x]<0xC0), None)
      if minx is not None:
         maxx = next((x for x in xrange(maxw-1, minx-1, -1) if line[x]<0xC0), None)
      ranges.append((minx, maxx))
   return ranges


def deepcopy(object):
   """Deep copy an object.  We know that the object is a dictionary with
    some elements that are lists and some that lists of lists.  By using
    this information, we can copy the object faster than copy.deepcopy.
   Enter: object: the dictionary object to copy.
   Exit:  object_copy: the copy of the object."""
   newobj = copy.copy(object)
   for key in newobj:
      if isinstance(newobj[key], list):
         if len(newobj[key]) and isinstance(newobj[key][0], list):
            newobj[key] = [val[:] for val in object[key]]
         else:
            newobj[key] = object[key][:]
   return newobj


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
   if 'task' in current and TasksLeft is not None:
      digits = TaskDigits.value
      out.append('%*d:%*d'%(digits, current['task'], digits, TasksLeft.value))
   out = " ".join(out)
   return out


def load_file(file, width, gap, verbose=0, priority=None, num=None):
   """Load a file, generating a mask for it.
   Enter: file: the path of the file to load.
          width: the width of the final board.
          gap: the width of the mask to add to each file.
          verbose: the verbosity for output.
          priority: the priority for this process.
          num: the number to assign this file.  None for auto-numbering.
   Exit:  part: the new part record"""
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
   part['ranges'] = calculate_ranges(pixels)
   mask = blank_image(part['w']+gap*2, part['h']+gap*2)
   check = []
   for dy in xrange(-gap, gap+1):
      for dx in xrange(-gap, gap+1):
         if dx*dx+dy*dy<=(gap+0.5)*(gap+0.5):
            check.append((dx, dy))

   starttime = time.time()
   for (dx, dy) in check:
      if verbose>=2:
         sys.stdout.write("%3d,%3d %s  \r"%(dx, dy, file))
         sys.stdout.flush()
      add_image(mask, pixels, dx+gap, dy+gap, maxval=0xC0)

   part['mask'] = mask
   if verbose>=3:
      write_ppm(file+'.data.ppm', part['data'])
      write_ppm(file+'.mask.ppm', part['mask'])
   part['num'] = num
   if verbose>=1:
      print "%5.3fs to create mask for %d: %s (%d x %d)"%(time.time()-starttime, part['num'], file, part['w'], part['h'])
   return part


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
   parts = [None]*len(files)
   if multiprocess:
      kwarg = {}
      if multiprocess is not True:
         kwarg['processes'] = multiprocess
      pool = multiprocessing.Pool(initializer=worker_init, **kwarg)
      tasks = []
   else:
      pool = None

   try:
      num = 0
      for file in files:
         if pool:
            tasks.append(pool.apply_async(load_file, args=(file, width, gap, verbose, priority, num)))
         else:
            part = load_file(file, width, gap, verbose, num=num)
            parts[part['num']] = part
         num += 1
      if pool:
         pool.close()
         for task in tasks:
            part = task.get()
            parts[part['num']] = part
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


def overlap_image(base, sub, x0, y0, fliph=False, flipv=False, maxval=0xC0, ranges=None, baseranges=None):
   """Check if a sub image overlaps a base image.
   Enter: base: the base image in [y][x] format.  Modified.
          sub: the image to add in [y][x] format.
          x0, y0: position within the base image that the upper left of
                  the sub image will be located.  May be negative.
          flipx, flipv: flip the sub image along one of the axes.
          maxval: any value equal to or above this is ignored.
          ranges: an array that has one tuple per line in the sub image
                  with each tuple containing the left-most and right-most
                  pixels in that line that are below maxval.
          baseranges: the ranges array for the base image.
   Exit:  overlaps: True if the image overlaps, False if it doesn't"""
   bh = len(base)
   sw = len(sub[0])
   sh = len(sub)
   swm1 = sw-1
   shm1 = sh-1
   for y in xrange(sh):
      by = y+y0
      (minbx, maxbx) = baseranges[by]
      if maxbx is None:
         continue
      maxbx = maxbx+1-x0
      if flipv:
         (minx, maxx) = ranges[shm1-y]
      else:
         (minx, maxx) = ranges[y]
      if fliph:
         (minx, maxx) = (swm1-maxx, swm1-minx)
      if maxbx<=minx:
         continue
      maxx += 1
      minbx = minbx-x0
      if minbx>minx:
         minx = minbx
      if maxbx<maxx:
         maxx = maxbx
      if maxx<=minx:
         continue
      if flipv:
         line = sub[shm1-y]
      else:
         line = sub[y]
      baseline = base[by]
      if fliph:
         for x in xrange(minx, maxx):
            if baseline[x+x0]<maxval and line[swm1-x]<maxval:
               return True
      else:
         for x in xrange(minx, maxx):
            if baseline[x+x0]<maxval and line[x]<maxval:
               return True
   return False


def process_image(current, parts, partnum, best, pool=None, tasks=None):
   """Process an image.
   Enter: current: the current layout state.
          parts: the list of parts to process in order.
          partnum: the 0-based index into the parts to process.
          best: a dictionary with the best result so far; can be changed.
          pool: multiprocessing pool, if this is the main task.
          tasks: an array of started tasks used with the pool."""
   if pool:
      if partnum>=current.get('stage', 0.5):
         current['task'] = len(tasks)
         tasks.append(pool.apply_async(process_image_task, args=(current, parts, partnum, best)))
         tasks[-1].task_num = current['task']
         TasksLeft.value = len(tasks)
         TaskDigits.value = len('%d'%len(tasks))
         return
   if not 'order' in current:
      current['order'] = range(len(parts))
   if not 'data' in current:
      current['data'] = blank_image(best['w'], current['height'])
   if not 'mask' in current:
      current['mask'] = blank_image(best['w'], current['height'])
      current['ranges'] = [(None, None)]*current['height']
   left = current['order'][partnum:]
   for part in left:
      newcur = deepcopy(current)
      newcur['order'][partnum] = part
      remaining = left[:]
      remaining.remove(part)
      newcur['order'][partnum+1:] = remaining
      if part:
         orientrange = 4
      else:
         orientrange = 1
      for orient in xrange(orientrange):
         if pool:
            if partnum+0.5>=newcur.get('stage', 0.5):
               taskcur = deepcopy(newcur)
               taskcur['task'] = len(tasks)
               tasks.append(pool.apply_async(process_image_orient_task, args=(taskcur, parts, partnum, best, (orient&1)==1, (orient&2)==2)))
               tasks[-1].task_num = taskcur['task']
               TasksLeft.value = len(tasks)
               TaskDigits.value = len('%d'%len(tasks))
               continue
         process_image_orient(newcur, parts, partnum, best, (orient&1)==1, (orient&2)==2, pool, tasks)


def process_image_orient(current, parts, partnum, best, fliph, flipv, pool=None, tasks=None):
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
          pool: multiprocessing pool, if this is the main task.
          tasks: an array of started tasks used with the pool."""
   gap = current['gap']
   height = current['height']
   verbose = current['verbose']
   group_key = tuple([parts[index]['num'] for index in current['order'][partnum:]])
   group_w = current['widths'].get(group_key, None)
   part = parts[current['order'][partnum]]
   numparts = len(parts)
   xmin = current['lastx']
   allow_overlap_termination = True
   if partnum>0:
      allow_overlap_termination = False
      for xpart in xrange(0, partnum):
         start_group_key = tuple([parts[index]['num'] for index in current['order'][xpart:partnum+1]])
         start_group_xmin = current['widths_xmin'].get(start_group_key, None)
         if start_group_xmin:
            start_xmin = current['state'][xpart]['x']+start_group_xmin
            if start_xmin>xmin:
               xmin = start_xmin
               allow_overlap_termination = True
   for x in xrange(xmin, current['maxw']+1):
      bestw = best['w']
      if TaskBestW:
         taskbestw = TaskBestW.value
         if taskbestw<bestw:
            bestw = taskbestw
      if bestw in current['widths_values']:
         return
      if group_w and x+group_w>=bestw:
         break
      if x+part['w']>=bestw:
         break
      overlapped = False
      ymin = 0
      if x==current['lastx']:
         ymin = current['lasty']
         if partnum and current['order'][partnum]>current['order'][partnum-1]:
            ymin += 1
         if ymin:
            # Don't trigger the end-of-search on this path
            overlapped = True
      for y in xrange(ymin, height-part['h']+1):
         if overlap_image(current['mask'], part['data'], x, y, fliph, flipv, ranges=part['ranges'], baseranges=current['ranges']):
            overlapped = True
            continue
         newcur = deepcopy(current)
         add_image(newcur['data'], part['data'], x, y, fliph, flipv)
         add_image(newcur['mask'], part['mask'], x-gap, y-gap, fliph, flipv)
         newcur['lastx'] = x
         newcur['lasty'] = y
         newcur['maxw'] = max(newcur['maxw'], x+part['w']+gap)
         newcur['w'] = max(newcur['w'], x+part['w'])
         newcur['ranges'] = calculate_ranges(newcur['mask'], newcur['w']+gap)
         newcur['state'].append({'num':part['num'], 'fliph':fliph, 'flipv':flipv, 'x':x, 'y':y})
         if verbose>=5 or ((verbose>=2 or (verbose>=1 and partnum+1==numparts)) and (not 'task' in newcur or (TaskWatch is not None and newcur['task']==TaskWatch.value))):
            curtime = time.time()
            if verbose>=4 or curtime-best.get('laststatus', 0)>=1:
               state = get_state(newcur, best)
               sys.stdout.write('%-79s\r'%state[-79:])
               sys.stdout.flush()
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
            continue
         if partnum+1==numparts:
            best['w'] = newcur['w']
            best['data'] = newcur['data']
            # This could have been changed by another process, so make sure
            if TaskBestW is not None and newcur['w']<TaskBestW.value:
               with TaskBestW.get_lock():
                  if newcur['w']<TaskBestW.value:
                     TaskBestW.value = newcur['w']
            if verbose>=3 or (verbose>=1 and current['parts']==current['totalparts']):
               print get_state(newcur, best)
               print 'Current best width: %d '%best['w']
            if verbose>=3 or (verbose>=2 and current['parts']==current['totalparts']):
               write_ppm('current'+current['out'], best['data'], best['w'], verbose=verbose)
         else:
            process_image(newcur, parts, partnum+1, best, pool=pool, tasks=tasks)
      # This optimization is only correct if the parts are individually
      #            contiguous and avoid other conditions.  An example on the
      # 0  11111   left with three parts with a gap of 1, the solution shown
      # 0      1   will never be reached with a width of 8.  Rather, part 2
      # 000 22 1   will end up to the right of part 1 with a width of 10.
      if allow_overlap_termination and not overlapped:
         break


def process_image_orient_task(current, parts, partnum, best, fliph, flipv):
   """Process an image, returning the result.
   Enter: current: the current layout state.
          parts: the list of parts to process in order.
          partnum: the 0-based index into the parts to process.
          best: a dictionary with the best result so far; can be changed.
          fliph, flipv: the orientation of the image for processing.
   Exit:  best: best layout found in this task."""
   if current['priority']:
      set_priority(current['priority'])
   process_image_orient(current, parts, partnum, best, fliph, flipv)
   if current['verbose']>=2 and TaskWatch is not None and current['task']==TaskWatch.value:
      state = get_state(current, best)
      sys.stdout.write('%-79s\r'%state[-79:])
      sys.stdout.flush()
   return best


def process_image_task(current, parts, partnum, best):
   """Process an image, returning the result.
   Enter: current: the current layout state.
          parts: the list of parts to process in order.
          partnum: the 0-based index into the parts to process.
          best: a dictionary with the best result so far; can be changed.
   Exit:  best: best layout found in this task."""
   if current['priority']:
      set_priority(current['priority'])
   process_image(current, parts, partnum, best)
   if current['verbose']>=2 and TaskWatch is not None and current['task']==TaskWatch.value:
      state = get_state(current, best)
      sys.stdout.write('%-79s\r'%state[-79:])
      sys.stdout.flush()
   return best


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
      global TasksLeft, TaskDigits, TaskWatch, TaskBestW
      TasksLeft = multiprocessing.Value('i', 0)
      TaskDigits = multiprocessing.Value('i', 1)
      TaskWatch = multiprocessing.Value('i', -1)
      TaskBestW = multiprocessing.Value('i', Best['w'])
      kwarg = {}
      if Multiprocess is not True:
         kwarg['processes'] = Multiprocess
      pool = multiprocessing.Pool(initializer=worker_init, initargs=(TasksLeft, TaskDigits, TaskWatch, TaskBestW), **kwarg)
      tasks = []
   else:
      pool = None
      tasks = None

   try:
      current = deepcopy(Current)
      process_image(current, Parts, 0, Best, pool, tasks)
      del current
      if pool:
         pool.close()
         while len(tasks):
            try:
               tasks[0].get(timeout=1)
            except Exception:
               pass
            for t in xrange(len(tasks)-1, -1, -1):
               if tasks[t].ready():
                  partbest = tasks[t].get()
                  if partbest['w']<Best['w']:
                     Best['w'] = partbest['w']
                     Best['data'] = partbest['data']
                     if Best['w']<TaskBestW.value:
                        with TaskBestW.get_lock():
                           if Best['w']<TaskBestW.value:
                              TaskBestW.value = Best['w']
                  tasks[t:t+1] = []
            TasksLeft.value = len(tasks)
            if len(tasks):
               TaskWatch.value = tasks[0].task_num
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
      elif priority=='above' or (nice is not None and nice>=-10):
         level = psutil.ABOVE_NORMAL_PRIORITY_CLASS
      elif priority=='high' or (nice is not None and nice>=-18):
         level = psutil.HIGH_PRIORITY_CLASS
      else:
         level = psutil.NORMAL_PRIORITY_CLASS
   else:
      priorities = {'idle': 19, 'low': 10, 'normal': 0, 'above': -10, 'high': -18}
      if nice is not None:
         level = nice
      elif priority in priorities:
         level = priorities[priority]
      else:
         level = 0
   proc = psutil.Process(os.getpid())
   proc.nice(level)


def worker_init(tasks_left=None, task_digits=None, task_watch=None, task_best_w=None):
   """Supress the ctrl-c signal in the worker processes, and record the
    shared memory objects.
   Enter: tasks_left: shared memory object."""
   global TasksLeft, TaskDigits, TaskWatch, TaskBestW

   signal.signal(signal.SIGINT, signal.SIG_IGN)
   if tasks_left:
      TasksLeft = tasks_left
   if task_digits:
      TaskDigits = task_digits
   if task_watch:
      TaskWatch = task_watch
   if task_best_w:
      TaskBestW = task_best_w


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
   Beat = None
   Multiprocess = False
   Stage = 1
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
      elif arg.startswith('--out='):
         OutFile = arg.split('=', 1)[1]
      elif arg.startswith("--priority="):
         Priority = arg.split('=', 1)[1]
      elif arg.startswith("--stage="):
         Stage = float(arg.split("=", 1)[1])
      elif arg=="-v":
         Verbose += 1
      elif arg.startswith('-'):
         Help = True
      else:
         Files.append(arg)
   if Help or not len(Files):
      print """Compute best-fit lumber usage.

Syntax: boardfit.py (ppm files ...) --height=(height of board) --gap=(gap size)
                    --beat=(length) --multi[=(workers)] --stage=(stage) --gif
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
--out specifies the name of the output ppm.  An additional file current(out) is
  written whenever a local best is obtained.
--priority asks the program to run at a particular priority level.  Options are
  'normal', 'low', 'idle', or a nice-like number.
--stage specifies at what point multiprocessing should call subprocesses.
  Default is 1, which calculates where one part can be before calling the
  subprocesses.  Half values can be used to indicate partial part processing.
-v increases the verbosity."""
      sys.exit(0)

   if Priority and not Multiprocess:
      set_priority(Priority)

   Parts = load_files(Files, Height, Gap, Verbose, Multiprocess, Priority)

   Current = {'gap': Gap, 'height': Height, 'verbose': Verbose, 'gif': GenerateGIF, 'out': OutFile, 'multiprocess': Multiprocess, 'beat': Beat, 'stage': Stage, 'priority': Priority, 'totalparts': len(Parts)}
   Best = {}

   Current['widths'] = {}
   Current['widths_xmin'] = {}
   for part in Parts:
      Current['widths'][(part['num'], )] = part['w']
      Current['widths_xmin'][(part['num'], )] = 0
   Current['widths_values'] = dict.fromkeys(Current['widths'].values())
   for comblen in xrange(2, len(Parts)):
      for combo in itertools.combinations(Parts, comblen):
         part_starttime = time.time()
         w = process_parts(combo, Current, {})
         xmin = w - max([part['w'] for part in combo])
         if Verbose>=2:
            out = 'Partial: %s %d (%3.1fs)'%(str(tuple([part['num'] for part in combo])), w, time.time()-part_starttime)
            print "%-79s"%out
         keys = [part['num'] for part in combo]
         for perm in itertools.permutations(keys):
            Current['widths'][perm] = w
            Current['widths_xmin'][perm] = xmin
            left_w = Current['widths'][tuple([part['num'] for part in combo if part['num']!=perm[-1]])]
            if w > left_w:
               Current['widths_xmin'][perm] = w - Parts[perm[-1]]['w']
      if Verbose>=3:
         print "Widths"
         pprint.pprint(Current['widths'])
         print "Widths XMin"
         pprint.pprint(Current['widths_xmin'])
      Current['widths_values'] = dict.fromkeys(Current['widths'].values())

   process_parts(Parts, Current, Best)

   write_ppm(Current['out'], Best['data'], Best['w'])
   print 'Best width: %d (%3.1fs)'%(Best['w'], time.time()-starttime)

