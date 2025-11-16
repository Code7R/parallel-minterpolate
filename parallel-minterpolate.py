#!/usr/bin/python

# native
import argparse
import datetime
import os
import subprocess
import json

parser = argparse.ArgumentParser(
    description='Parallelize video frame interpolation with FFmpeg.')
parser.add_argument('inputVideo',
                    type=argparse.FileType('r'),
                    help='an input video file')
parser.add_argument('--split',
                    metavar='N',
                    type=int,
                    required=False,
                    default=os.cpu_count(),
                    help='number of tasks to generate equally')
parser.add_argument('-o, --outputDir',
                    metavar='NAME',
                    default='output',
                    dest="outputDir",
                    help='name of the output directory, default=\'output\'')
parser.add_argument('--fps',
                    metavar='N',
                    type=int,
                    default=60,
                    help='target FPS, default=60')
parser.add_argument('--shutdown',
                    action='store_true',
                    help='shutdown computer after tasks are completed (n/a in bash mode')
parser.add_argument('--autoname', "-A",
                    action='store_true',
                    help="Choose a name based in the input's filename (default: use final.mkv as filename)")
args = parser.parse_args()

probeResult = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", "-print_format", "json", args.inputVideo.name], stdout=subprocess.PIPE, text=True)
probed = json.loads(probeResult.stdout)
#print(repr(probed))

ffmpeg = "ffmpeg -y"

# minterpolate breaks on generic "-map 0" argument, working around it
avmap = ""

videoSeconds = float(probed['format']['duration'])

for l in probed['streams']:
    ct = l.get('codec_type', '')
    if ct == 'audio' or ct == 'video':
        avmap += " -map 0:" + str(l['index'])

#exit(f"Dbg: {avmap}")

# calculate duration of the split parts
partsSeconds = round(videoSeconds / args.split)
partsTime = datetime.timedelta(seconds=partsSeconds)

odir = os.path.abspath(os.path.normpath(args.outputDir))

os.makedirs(odir, exist_ok=True)

ifile = os.path.abspath(os.path.normpath(args.inputVideo.name))

# create and write the input text file for ffmpeg concat
f = open(os.path.join(odir, "list.txt"), 'w')
for i in range(args.split):
    f.write(f"file 'output{str(i).zfill(3)}.{args.fps}fps.mkv'\n")
f.close()

use_bash = False

if args.autoname:
    oname_stem, oname_ext = os.path.splitext(os.path.basename(args.inputVideo.name))
    oname = f"{oname_stem}.{args.fps}fps{oname_ext}"
else:
    oname = "final.mkv"

try:
    result = subprocess.run(["bash", "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    use_bash = bool(result) and ("GNU bash, " in result.stdout)
except:
    use_bash = False

if use_bash:
    script = "run.sh"
    ffmpeg = "nice -n18 " + ffmpeg
else:
    script = "run.bat"
script_abs = os.path.join(odir, script)

# write batch file
f = open(script_abs, 'w')

if use_bash:
    f.write("#!/bin/sh -ex\n")

f.write(f"cd \"{odir}\"\n")

f.write(
    f"{ffmpeg} -i \"{ifile}\" -c copy {avmap} -segment_time {partsTime} -f segment -reset_timestamps 1 output%03d.mkv\n")

# launch all ffmpeg tasks in parallel
# continue only when everything is finished

if not use_bash:
    f.write('(\n')

for i in range(args.split):
    if use_bash:
        fork_pfx = ""
        fork_sfx = f"& ff_pid_{i}=$!\n"
    else:
        fork_pfx =  f"  start \"TASK {i+1}\" "
        fork_sfx = ""
    f.write(
        f"  {fork_pfx} {ffmpeg} -i output{str(i).zfill(3)}.mkv {avmap} -crf 10 -vf \"minterpolate=fps={args.fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1\" output{str(i).zfill(3)}.{args.fps}fps.mkv{fork_sfx}\n")

if use_bash:
    f.writelines(map(lambda i: f"wait $ff_pid_{i};\n", range(args.split)))
else:
    f.write(') | pause\n')

if not use_bash:
    f.write('timeout /t 3 /nobreak > nul\n')

f.write(f'{ffmpeg} -f concat -safe 0 -i list.txt -c copy -map 0 \"{oname}\"\n')

if args.shutdown and not use_bash:
    f.write('timeout /t 3 /nobreak > nul\n')
    f.write('shutdown /s /f /t 0\n')
f.close()

# execute batch file
os.chdir(odir)
if use_bash:
    subprocess.Popen(["bash", script_abs])
else:
    subprocess.Popen(script_abs)
