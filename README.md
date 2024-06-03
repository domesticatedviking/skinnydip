# We did it!
On March 20, 2024, Prusa incorporated its own version of Skinnydip in firmware 2.7.3-alpha1.
Gratitude to Prusa for acknowledging this project in the release notes.  Prusa devs are classy. https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.7.3-alpha1

# Announcement:
Skinnydip is now a built in feature for SuperSlicer (formerly Slic3r++) which can be downloaded [here](https://github.com/supermerill/Slic3r/releases).   Many thanks to Supermerill for his tremendous work over the years adding experimental features to our beloved PrusaSlicer.

 If you wish to see Skinnydip in an official build of PrusaSlicer, I suggest you leave a polite comment [here](https://github.com/prusa3d/PrusaSlicer/issues/2385). 

# The docs below are for the (now no longer maintained) python post-processing script
This script has fulfilled its goal of being a proof of concept, however, the heuristics it uses to find necessary gcode injection locations are not 100% accurate.   Perhaps with sufficient research the regular expressions that are used could make this a more complete solution, but there isn't really any good reason for the effort it would take to do that now that there is a robust and reliable solution in SuperSlicer.

# SKINNYDIP MMU2 string eliminator v1.0.5 beta
a post processing script for Slic3r PE / PrusaSlicer to remove fine threads from filament tips during MMU2 toolchanges.
Written by Erik Bjorgan based on a core concept from David Shealey.
With love to the Prusa Community Forum and its incredible admin team.
http://facebook.com/groups/prusacommunity

  
# This tool is experimental, unmaintained, deprecated, and does not always work consistently.  Use it at your own risk -- better yet, use SuperSlicer! 
Tested with the following versions of Slic3r PE:
* 1.41.2+linux64
* 1.42.0-alpha7+linux64
* 1.42.0-alpha7+win64
* 1.42.0-beta1+linux64
* PrusaSlicer 2.0.0

While it is possible that it may work with other versions of Slic3r / PrusaSlicer, please do not assume this to be the case, as any changes to the gcode structure expected by this script could lead to gcode that has unintended effects, some of which could potentially be dangerous.

## Purpose:
This script is used to eliminate the stubborn threads of filament that
can jam the MMU2 during toolchanges  by providing a brief secondary dip
into the melt zone immediately after the cooling moves complete.   

## Installation:
### Dependencies
This script requires Python 2.7.  Linux users won't need to install anything.  Windows users can download v2.7.16 at https://www.python.org/downloads/ 

### Windows
Copy skinnydip.py to any folder eg ```C:\my\folder\skinnydip.py```
Unless python is in your system path you may need to find its location as well eg ```C:\python27\python.exe```

In Slic3rPE or PrusaSlicer's Print Settings > Output Options > Post Processing Scripts, use the following:

```C:\python27\python.exe C:\my\folder\skinnydip.py```

#### New:  Batch file for Windows users (recommended)
Some Windows users were reporting that parameters weren't being picked up correctly when filenames contained spaces.   This was determined to be due to [an issue with Slic3r PE](https://github.com/slic3r/Slic3r/issues/4000).  The included batch file (skinnydip.bat) should be saved in the same directory as skinnydip.py.  It attempts to locate your python installation automatically.   To call skinnydip with the windows batch file, in Slic3rPE > Print Settings > Output Options > Post Processing Scripts, use the following (change ```\path\to\``` to the actual directory first!)

```\path\to\skinnydip.bat```

This batch file also includes a pause at the end so that you can see the output of the post-processor before windows closes the command line window.  You will need to press any key for this window to close in order to resume using Slic3r.



### Linux / Mac
In Slic3r PE, provide the absolute path to the skinnydip.py script in Print Settings > Output Options > Post-processing scripts.     
for example:  ```/home/username/some_folder/skinnydip.py```
##### Known issue with installation on Linux appimage builds
At the time of this initial release some Linux appimage builds of Slic3r PE are misconfigured in a way that prevents running Python scripts directly.  Use ```/home/username/skinnydip_appimage_workaround.sh``` in the post processing script field instead.  This script should be located in the same folder as skinnydip.py
##### Permissions:
If you have issues with skinnydip.py or the workaround script running, you may need to update their permissions to mark them as executable. This can be done through the right-click menu or through the command line, ie:

```chmod +x skinnydip.py```

## Usage:
The script is configurable via comments made in the filament profile's start gcode section 
Every filament used for this script needs to have the following lines appear at the top of its filament start gcode.

```
M900 K{if printer_notes=~/.*PRINTER_HAS_BOWDEN.*/}200{else}30{endif}; Filament gcode
; SKINNYDIP CONFIGURATION START
; material_type PLA
; material_name my PLA Spool
; insertion_speed 2000 
; extraction_speed 4000
; insertion_pause 0 
; insertion_distance 41 
; removal_pause 0
; toolchange_temp off
; beep_on_dip off
; beep_on_temp off
; SKINNYDIP CONFIGURATION END
```
The most important parameter to configure correctly is "insertion_distance".  This distance is the depth that the filament is plunged back into the melt zone after the cooling moves complete.  The goal is to melt just the stringy part of the filament tip, not to remelt the entire tip, which would undo the shaping done by the cooling moves.   

If this number is too high, filament will be rammed out of the hotend onto the wipe tower, leaving blobs.   If it is too low, your tips will still have strings on them.


## How will I know the post processing script is configured correctly?
A successfully processed gcode file will have a header similar to the one below added to the beginning of the file.  Check this by opening the gcode file with a text editor.    If this header is not present, this means that your file has not been processed by the skinnydip script.  This is usually due to a problem with the way you've instructed Slic3r to run the script, but can also happen if Python 2.7 is not available on your system.

```
; SKINNYDIP THREAD REDUCTION v1.0.4 beta
; https://github.com/domesticatedviking/skinnydip
; Postprocessing completed on Wed May 29 21:05:14 2019
;               File Processed:/home/erik/PycharmProjects/skinnydip/01234.gcode
; Note that editing the values below will have no effect on your
; Skinnydip settings.  To change parameters you must reslice.

;         Configured extruders: ['T0', 'T1', 'T2', 'T3', 'T4']
;             Toolchange temps: [230, 231, 232, 233, 234]
;          Insertion distances: [50, 31, 31, 31, 31]
;      Auto insertion distance: 31.5
;       Total # of toolchanges: 83
;                   Dips added: 42
;       Toolchange temps added: 161
;   Tools beeping on skinnydip: None
; Tools beeping on temp change: None


```
## Known issues:

Skinnydip uses regular expressions to scan the gcode file for settings and places that it needs to insert commands.  It is very good at doing this when the input gcode has patterns that it expects to see, but it will also fail to insert commands if the gcode is not in the form expected.   You may find that there are some files that it fails to process properly, typically it will fail to apply a temperature change or add the skinnydip routine.   It would be GREATLY appreciated if you could attach the UNPROCESSED gcode files (sliced with the skinnydip settings included, but not processed by skinnydip.py) in your reports of these kinds of issues.   Thank you!!



## Explanation of configuration parameters:
|Parameter          |Explanation                                              |Default Value |
|--------------------|----------------------------------------------------------|---------------|
material_type     | Name of type of material                                    | n/a
material_name     | User defined name for this filament                         | n/a
insertion_speed   | Speed at which the filament enters the melt zone after cooling moves are finished. | 2000 (mm/min)
extraction_speed  | Speed at which the filament leaves the melt zone.  Faster is generally better | 4000 (mm/min)           
insertion_pause   | Time to pause in the melt zone before extracting the filament.| 0 (milliseconds) |
insertion_distance| Distance in mm for filament to be inserted into the melt zone.  This setting is hardware and assembly specific, so it must be determined experimentally.  For stock extruders, use 40-42mm. For bondtech BMG extruders, use 30-32mm.  If blobs appear on the wipe tower or stringing starts getting worse rather than better, this value should be reduced.   | n/a
removal_pause     | Number of milliseconds to pause in the cooling zone prior to extracting filament from hotend.  This pause can be helpful to allow the filament to cool prior to being handled by the bondtech gears. |  0 (milliseconds)
toolchange_temp   | Temperature to extract filament from the hotend.  Cooler temperatures are associated with better tips. | off
beep_on_dip       | Play a tone through the printer's speaker to signal when a skinnydip move is taking place (for debug purposes) |off (off/on)  |
beep_on_temp      | Play a tone when a toolchange temperature setting has been applied (for debug purposes)  | off (off/on)|
                  
## Goals:
This method is highly effective for removing fine strings of filament, but my hope is that this script will only be needed for a short time.  My ultimate goal is to integrate these features into Slic3r/PrusaSlicer, for both ease of use and accuracy of output.  
