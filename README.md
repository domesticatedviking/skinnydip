# SKINNYDIP MMU2 string eliminator
a post processing script for Slic3r PE to remove fine threads from filament tips during MMU2 toolchanges.
Written by Erik Bjorgan based on a core concept from David Shealey.
With love to the Prusa Community Forum and its incredible admin team.
http://facebook.com/groups/prusacommunity

# While this tool is becoming more and more stable, it is still experimental.  Use it at your own risk! 
Tested with the following versions of Slic3r PE:
* 1.41.2+linux64
* 1.42.0-alpha7+linux64
* 1.42.0-alpha7+win64

While it is possible that it may work with other versions of Slic3r, please do not assume this to be the case, as any changes to the gcode structure expected by this script could lead to gcode that has unintended effects, some of which may be dangerous.   If you choose to use this, I salute you!

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

In Slic3rPE > Print Settings > Output Options > Post Processing Scripts, use the following:

```C:\python27\python.exe C:\my\folder\skinnydip.py```



### Linux
In Slic3r PE, provide the absolute path to the skinnydip.py script in Print Settings > Output Options > Post-processing scripts.   
eg.  ```/home/username/some_folder/skinnydip.py```
##### Known issue with installation on Linux appimage builds
At the time of this initial release some Linux appimage builds of Slic3r PE are misconfigured in a way that prevents running Python scripts directly.  Use ```/home/username/skinnydip_appimage_workaround.sh``` in the post processing script field instead.  This script should be located in the same folder as skinnydip.py

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
; insertion_distance auto 
; removal_pause 0
; toolchange_temp 0
; beep_on_dip off
; beep_on_temp off
; SKINNYDIP CONFIGURATION END
```

## Explanation of configuration parameters:
|Parameter          |Explanation                                              |Default Value |
|--------------------|----------------------------------------------------------|---------------|
material_type     | Name of type of material                                    | n/a
material_name     | User defined name for this filament                         | n/a
insertion_speed   | Speed at which the filament enters the melt zone after cooling moves are finished. | 2000 (mm/min)
extraction_speed  | Speed at which the filament leaves the melt zone.  Faster is generally better | 4000 (mm/min)           
insertion_pause   | Time to pause in the melt zone before extracting the filament.| 0 (milliseconds) |
insertion_distance| Distance in mm for filament to be inserted into the melt zone.  This is hardware specific, and shouldn't change very much from one material to the next.  If blobs appear on the wipe tower, this setting is probably too high. For stock extruder users, David reports that  (Cooling Tube Position+(0.5 * Cooling tube length)) - 1.5) is a good value to use here.  Automatic calculation of this value is on the todo list  | auto (usually approx 33.5mm)
removal_pause     | Number of milliseconds to pause in the cooling zone prior to extracting filament from hotend.  This pause can be helpful to allow the filament to cool prior to being handled by the bondtech gears. |  0 (milliseconds)
toolchange_temp   | Temperature to extract filament from the hotend.  Cooler temperatures are associated with better tips. | N/A
beep_on_dip       | Play a tone through the printer's speaker to signal when a skinnydip move is taking place (for debug purposes) |off (off/on)  |
beep_on_temp      | Play a tone when a toolchange temperature setting has been applied (for debug purposes)  | off (off/on)|
                  
## Goals:
This method is highly effective for removing fine strings of filament.
This script is intended as a proof of concept, with the hopes that this
functionality would be added to a future revision of Slic3r PE.




