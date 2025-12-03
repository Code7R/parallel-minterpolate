#!/usr/bin/python

# native
import argparse
import datetime
import os
import subprocess
import json

ffmpeg = "ffmpeg -y"

try:
    result = subprocess.run(["bash", "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    use_bash = bool(result) and ("GNU bash, " in result.stdout)
    ffmpeg = "nice -n18 " + ffmpeg
    script = "run.sh"
except:
    use_bash = False
    script = "run.bat"

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
parser.add_argument('-F, --ffmpeg-cmd',
                    metavar='CMD',
                    default=ffmpeg,
                    dest="ffmpeg",
                    help=f'ffmpeg command to use (default: "{ffmpeg}")')
args = parser.parse_args()

probeCmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", "-print_format", "json", args.inputVideo.name]
#print(" ".join(probeCmd))
probeResult = subprocess.run(probeCmd, stdout=subprocess.PIPE, text=True)
probed = json.loads(probeResult.stdout)
#print(repr(probed))


odir = os.path.abspath(os.path.normpath(args.outputDir))
os.makedirs(odir, exist_ok=True)
ifile = os.path.abspath(os.path.normpath(args.inputVideo.name))

videoSeconds = float(probed['format']['duration'])

input_subs = ''
# minterpolate breaks with auto-detecting "-map 0" argument, therefore explicitly pick the subs in the end
map_subs = ''
map_audio = ''
map_video = ''

for l in probed['streams']:
    ct = l.get('codec_type', '')
    #print(f"ct: {ct}")
    if ct == 'audio' and not map_audio:
        map_audio = '-map 0:a'
    elif ct == 'video' and not map_video:
        map_video = '-map 0:v'
    elif ct == 'subtitle' and not input_subs:
        input_subs = f'-i "{ifile}"'
        map_subs = '-map 1:s'
    if map_video and map_audio and map_subs:
        break

# calculate duration of the split parts
partsSeconds = round(videoSeconds / args.split)
partsTime = datetime.timedelta(seconds=partsSeconds)

# create and write the input text file for ffmpeg concat
f = open(os.path.join(odir, "list.txt"), 'w')
for i in range(args.split):
    f.write(f"file 'output{str(i).zfill(3)}.{args.fps}fps.mkv'\n")
f.close()

if args.autoname:
    oname_stem, oname_ext = os.path.splitext(os.path.basename(args.inputVideo.name))
    oname = f"{oname_stem}.{args.fps}fps{oname_ext}"
else:
    oname = "final.mkv"

script_abs = os.path.join(odir, script)

# write batch file
f = open(script_abs, 'w')

if use_bash:
    f.write("#!/bin/sh -ex\n")

f.write(f"cd \"{odir}\"\n")

f.write(
    f"{args.ffmpeg} -i \"{ifile}\" -c copy {map_video} {map_audio} -segment_time {partsTime} -f segment -reset_timestamps 1 output%03d.mkv\n")

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
        f"  {fork_pfx} {args.ffmpeg} -i output{str(i).zfill(3)}.mkv {map_video} {map_audio} -crf 10 -vf \"minterpolate=fps={args.fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1\" output{str(i).zfill(3)}.{args.fps}fps.mkv{fork_sfx}\n")

if use_bash:
    f.writelines(map(lambda i: f"wait $ff_pid_{i};\n", range(args.split)))
else:
    f.write(') | pause\n')

if not use_bash:
    f.write('timeout /t 3 /nobreak > nul\n')

f.write(f'{args.ffmpeg} -f concat -safe 0 -i list.txt {input_subs} -c copy {map_video} {map_audio} {map_subs} \"{oname}\"\n')

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
