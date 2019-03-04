# SKINNYDIP MMU2 string eliminator
a post processing script for Slic3r PE to remove fine threads from filament tips during MMU2 toolchanges.
Written by Erik Bjorgan based on a core concept from David Shealey.
With love to the Prusa Community forum and its incredible admin team.
http://facebook.com/groups/prusacommunity

## Purpose:
This script is used to eliminate the stubborn threads of filament that
can jam the MMU2 during toolchanges  by providing a brief secondary dip
into the melt zone immediately after the cooling moves complete.   

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
; insertion_distance 31 
; removal_pause 0
; SKINNYDIP CONFIGURATION END
```

## Explanation of configuration parameters:
| Parameter          | Explanation                                              |
|--------------------|----------------------------------------------------------|
material_type     | Name of type of material 
material_name     | User defined name for this filament
insertion_speed   | Speed (mm/m) at which the filament enters the melt zone after cooling moves are finished. default        speed is 2000mm/m 
extraction_speed  | Speed (mm/m) at which the filament leaves the melt zone.  Faster is generally better (4000mm/min)           
insertion_pause   | Number of milliseconds to pause in the melt zone before extracting the filament.  0 is the default.              insertion_distance| Distance in mm for filament to be inserted into the melt zone.  This is hardware specific, and shouldn't change very much from one material to the next.  31mm is the default setting (tested on BMG extruder).  If blobs appear on the wipe tower, this setting is probably too high.                                                    |
removal_pause     | Number of milliseconds to pause in the cooling zone prior to extracting filament from hotend.  This pause can be helpful to allow the filament to cool prior to being handled by the bondtech gears.                           |
                  
## Goals:
This method is highly effective for removing fine strings of filament.
This script is intended as a proof of concept, with the hopes that this
functionality would be added to a future revision of Slic3r PE.


