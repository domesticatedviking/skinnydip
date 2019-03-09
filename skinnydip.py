#!/usr/bin/python
# coding=utf8
"""
Skinnydip MMU2 String Eliminator
A post processing script for Slic3r Prusa Edition and the Original Prusa MMU2
Written by Erik Bjorgan based on a core concept from David Shealey.
With love to the Prusa Community forum and its incredible admin team.
http://facebook.com/groups/prusacommunity


GNU PUBLIC LICENSE: 

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

"""
Slic3r single extruder MMU parameters - a glossary.  

filament parking position: The distance from the tip of the nozzle to just beyond the bondtech gears.
                           This value may differ from one style of extruder to the next.
cooling tube length:       Length of the stroke during the cooling moves (moves up and down by this amount)
cooling tube position:     Distance from the tip of the nozzle to the bottom of the cooling tube.
                           All E3D V6 hotends should use roughly the same number.
extra loading distance:    This distance is usually a negative number. It causes the filament to stop
                           short of the end of the nozzle during a tool change, to avoid pushing out residual
                           filament and causing blobs on the wipe tower.

ANATOMY OF an unload on an E3D V6 hotend
    
/2   5_|__|___________________________________________________62.3mm_________________________                         
 ||  | |           |          |   35mm    |                   heat sink        Parking pos(85)
 |   | |                      |coolingtube|                   |                      |
0mm  |    10        20        30    |   40        50        60        70        80        90
 |   | 6.5---12.5 
     | nozzle threads                    | TORLON / PTFE TUBES      |68.63mm
 |___|_|____|12.5__|_________________________________________________top of PTFE_____|_______
\||__|_|____|______17.5   heatbreak______|___________________________________________________
       |6.5-|     |                      |37.8       
       |___block__|       
    
1. Extract a total of 35mm in smaller moves.  (35 = tube retraction + 0.5 * tube length) 
 --------------->------------->--->->(-35mm total) 
           -15mm       -14mm -4mm-2mm

2. Move filament down and then up in the cooling tube for cooling tube length 
                       10mm<---------
                           --------->-10mm  (repeats * number of cooling moves)                                                   

2.5- SKINNYDIP ONLY: move the filament back down into the hot zone to melt off stringy tips:
      <------------------------------(eg. 31mm)
      (optionally pause)
      ------------------------------>(eg. -31mm)
      then return to the cooling tube.
                                    (optionally pause again)                                   
                                   
3. Retract the rest of the way out of the extruder to parking pos                   |total -85mm
                             (-50mm)------------------------------------------------->
                            
It can be useful to perform step 1 at a lower temperature than your print temperature, as this
results in filament tips that are shorter and more uniform.

"""


"""
Notes to self:

Parameters set by Slic3r accessible in gcode  
; cooling_tube_length = 10      
; cooling_tube_retraction = 30  (Cooling tube position setting in Slic3r)      
; extra_loading_move = -13      (Extra loading distance in Slic3r)       
; parking_pos_retraction = 85   (Filament parking position in Slic3r)

Extraction behaviour:
retract -15,14,4,2  = 35mm.
retract -50 more    = 85mm.  = parking position (above bondtech gears)      

Load behaviour:
insert 14.4 + 50 + 7.2 = 72mm
This falls short of the nozzle tip by 13mm (extra loading move of -13) 
 
"""


#  MODULES  ************************************************
from argparse import ArgumentParser
from bisect import bisect_left
import re
import pprint
import os
import sys
import time
from datetime import datetime
import shutil

#  CONSTANTS ************************************************
VERSION = "0.8.0 alpha"
TEST_FILE = None
RESOURCE_PATH = "/home/erik/PycharmProjects/skinnydip/testobjects/"
PROJECT_PATH = "/home/erik/PycharmProjects/skinnydip/"

TOOL_LIST = ["T0", "T1", "T2", "T3", "T4"]
DEFAULT_SETTINGS = {
    "material_type": "NOT CONFIGURED",
    "material_name": "default settings",
    "toolchange_temp": "-1",
    "print_temp": "-1",
    "insertion_speed": "2000",
    "extraction_speed": "4000",
    "insertion_pause": "0",
    "insertion_distance": "31",
    "removal_pause": "0",
    "beep_on_dip": "0",
    "beep_on_temp": "0",

}
NULL_SETTINGS_DICT = {
    "insertion_distance": "auto",
    "material_type": "N/A",
    "material_name": "not configured",
    "toolchange_temp": "-1",
    "print_temp": "-1",
    "insertion_speed": "0",
    "extraction_speed": "0",
    "insertion_pause": "0",
    "removal_pause": "0",
    "beep_on_dip": "0",
    "beep_on_temp": "0",
}
SAFE_RANGE = {
    "insertion_speed": [300, 10000],
    "extraction_speed": [300, 10000],
    "insertion_pause": [0, 20000],
    "insertion_distance": [0, 60, ["AUTO"]],
    "removal_pause": [0, 20000],
    "print_temp": [150, 295],
    "toolchange_temp": [150, 295, ['0', '-1']],
    }

TOOLCHANGE_TEMP_SAFE_RANGE = [150, 295]
SET_ITEMS = NULL_SETTINGS_DICT.keys()
VARS_FROM_SLIC3R_GCODE = ['cooling_tube_length', 'cooling_tube_retraction',
                          'extra_loading_move', 'parking_pos_retraction']
#M73 tolerant
INSERTIONS_REGEX = r"(?P<temp_pause>G1 E-.*\n)((G1 E-|M73).*\n){2,7}(M104 S(?P<filament_temp>.*)\n)?(?P<temp_restore>G1 [^E].*\n)(?:.*\n){1,20}(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
#INSERTIONS_REGEX =r"(?P<temp_pause>G1 E-.*\n)(.*\n){2,10}(M104 S(?P<filament_temp>\d\d\d)\n)?(?P<temp_restore>G1 [^E].*\n)(.*\n){1,20}(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
#INSERTIONS_REGEX = r"(?P<temp_pause>G1 E-.*\n)(?:G1 E-.*\n){1,}(M104 S(?P<filament_temp>\d\d\d)\n)?(?P<temp_restore>G1 [^E].*\n)(.*\n){1,20}(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
#INSERTIONS_REGEX=r"(?P<temp_pause>G1 E-.*\n)(?:G1 E-.*\n){1,}(?P<temp_restore>G1[^E].*\n)(M104 S(?P<filament_temp>\d\d\d))?(.*\n){1,20}(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
DOWN_BEEP = "M300 S5742 P195 ;downbeep\nM300 S3830 P95  ;downbeep\nM300 S1912 P95  ;downbeep\n"
UP_BEEP = "M300 S1912 P95  ;upbeep\nM300 S3830 P95  ;upbeep\nM300 S5742 P195 ;upbeep\n"
TEMP_BEEP = ["M300 S3038 P155 ;temp_beep\n","M300 S2550 P75 ;temp_beep\n"]
#DIP_AND_PAUSE_REGEX = r"(?P<temp_pause>G1 E-.*\n)(G1 E-.*\n){1,10}(.*\n){1,20}(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
CONFIGSTRING_REGEX = r"(SKINNYDIP CONFIGURATION START.?)(?P<configstring>.*)"
WAIT_FOR_TEMP_REGEX = r"(?P<wait_for_temp>^G1 E-\d\d.*\n)(^G1 E-.*$\n){1,30}M104 S.*"
TOOLCHANGE_TEMP_REGEX = r"M220 B.*\nM220 S(?P<speed_override>\d.*)\n(M.*\n)?(?P<temp_start>; CP TOOLCHANGE UNLOAD)"
#TOOLCHANGE_TEMP_REGEX = r"; CP TOOLCHANGE START\n; toolchange #(?P<toolchange_number>\d*\n);.*\n;.*\nM220 B\nM220 S(?P<speed_factor>\d*)\n(?P<temp_change_pos>; CP TOOLCHANGE UNLOAD)"
ASSOCIATE_TOOL_WITH_SETTINGS_REGEX = r"(?P<previous_tool>^T[01234].*$)(?P<otherstuff>(.*\n){40,100}); SKINNYDIP CONFIGURATION START.*\n(?P<parameters>(; .*\n){1,11});.?SKINNYDIP CONFIGURATION END"
COOLING_MOVE_REGEX = r"(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
TOOLCHANGE_REGEX = r"(?P<tool>^T[01234]$)"
FINAL_TOOLCHANGE_REGEX = r"G1 E.*\nG1.*\nG4 S0\n(?P<final>M2)20 R"  # NEEDS TO BE FIXED -M73
TEMPERATURE_REGEX = regex = r"; temperature = (...),(...),(...),(...),(...)"
FIRST_TOOL_SETTINGS_REGEX = r"\n(?P<first_tool>T[0-4])\nM.*\n;.*(SKINNYDIP CONFIGURATION START)\n(?P<config_string>(;.*\n)*)"
LINEBREAKS_REGEX = r"(?P<linebreak>\n)"

#  GLOBAL ****************************************************
logtext = ""


class CustomError(Exception):
    pass


class FileInfo():
    def __init__(self, target_file, **args):
        self.inputfilename = ""
        self.inputextension = ""
        self.inputfull = ""
        self.outputfilename = ""
        self.file_to_process = ""
        self.target_file = target_file
        self.f = None
        self.text = None
        self.lines = []
        self.outfile = None
        self.log_file_name = ""

        if self.target_file is not None:
            self.file_to_process = target_file
            self.keep_original = False
        else:
            self.parser = ArgumentParser()
            self.parser.add_argument(dest="myFile", help="open a file")
            self.parser.add_argument("--k", "--keep", action='store_true',
                                help="keep copy of original file")
            self.args = self.parser.parse_args()
            self.file_to_process = self.args.myFile
            self.keep_original = self.args.k
            self.myFile = self.args.myFile
            self.file_to_process = self.args.myFile

        if self.file_to_process is not None:
            self.inputfilename = os.path.splitext(self.file_to_process)[0]
            self.inputextension = os.path.splitext(self.file_to_process)[1]
            self.inputfull = self.inputfilename + self.inputextension
            self.outputfilename = self.inputfilename + "_skinnydip" + self.inputextension
            self.bakfilename = self.inputfilename + "_original" + self.inputextension
            lprint('File received for processing was {}'.format(self.file_to_process))
        else:
            lprint('No file received as an argument')

    def open_file_lines(self):
        self.f = open(self.file_to_process)
        self.lines = self.f.readlines()  #was .f.read()

    def open_file(self):
        self.f = open(self.file_to_process)
        self.text = str(self.f.read())

    def close_file(self):
        self.f.close()
        del self.text
        self.text=""

    def close_file_lines(self):
        self.f.close()
        del self.lines
        self.lines = []

    def write_output_file(self, contents):
        lprint("writing output to temporary file: " + self.outputfilename)
        self.outfile = open(self.outputfilename, 'w')
        self.outfile.write(contents)
        self.outfile.close()
        if self.keep_original:
            lprint("renaming original file as " + self.bakfilename)
            os.rename(self.inputfull, self.bakfilename)
        else:
            lprint("deleting original file: " + self.inputfull)
            os.remove(self.inputfull)
        lprint("moving post processed output to " + self.inputfull)
        os.rename(self.outputfilename, self.inputfull)

    def write_output_file_lines(self, contents):
        lprint("writing output to temporary file: " + self.outputfilename)
        self.outfile = open(self.outputfilename, 'w')
        self.outfile.writelines(contents)
        self.outfile.close()
        if self.keep_original:
            lprint("renaming original file as " + self.bakfilename)
            os.rename(self.inputfull, self.bakfilename)
        else:
            lprint("deleting original file: " + self.inputfull)
            os.remove(self.inputfull)
        lprint("moving post processed output to " + self.inputfull)
        os.rename(self.outputfilename, self.inputfull)


class SetupData():
    """
    Main data storage and configuration object
    """
    def __init__(self, target_file):
        self.configured_tools = []
        self.auto_insertion_distance = None
        self.log_file_name = None
        self.gcode_str = ""
        self.tool_settings = {}
        self.tc_dict = {}
        self.tc_list = []
        self.tc_lines = []
        self.toolnumber_sequence = []
        self.dip_index = {}
        self.dip_positions = []
        self.dip_lines = []
        self.temper_index = {}
        self.temper_positions = []
        self.temper_lines = []
        self.utool_settings = {}
        self.tool_settings = {}
        self.processed_gcode = ""
        self.target_file = target_file
        self.gcode_vars = {}
        self.final_insertion_list = []
        self.fileinfo=FileInfo(target_file)
        self.output_lines = []

    def sort_indexes(self):
        #self.temper_index = sorted(self.temper_index)
        #self.dip_index = sorted(self.dip_index)
        pass

    def apply_automatic_values(self):
        for tool in self.configured_tools:
            try:
                if str(self.tool_settings[tool]['insertion_distance']).upper() == "AUTO":
                    self.tool_settings[tool]['insertion_distance'] = self.auto_insertion_distance
            except:
                pass

    def open_target_file(self):
        self.fileinfo.open_file()
        self.gcode_str = self.fileinfo.text

    def open_target_file_lines(self):
        self.fileinfo.open_file_lines()
        self.gcode_lines = self.fileinfo.lines

    def check_target_file(self):
        if self.gcode_str[:11] == "; SKINNYDIP":
            raise CustomError("File was previously processed by this " + \
                              "script.  Terminating.")
        match = re.search("; SKINNYDIP CONFIGURATION START", self.gcode_str, re.MULTILINE)
        if not match:
            custom_message = "No skinnydip configuration data in target file.\n"
            custom_message += "Configuration must be set up in start gcode for filaments that will be used.\n"
            custom_message += "Please visit http://github.com/domesticatedviking/skinnydip to read the docs.\n"
            lprint(custom_message, error=True)

    def close_target_file(self):
        self.fileinfo.close_file()

    def close_target_file_lines(self):
        self.fileinfo.close_file_lines()

    def write_output_file(self):
        self.fileinfo.write_output_file(self.out)

    def write_output_file_lines(self):
        self.fileinfo.write_output_file_lines(self.output_lines)

    def init_log_file(self, filename):
        self.log_file_name = filename

    def write_log_file(self):
        logfile = open("skinnydip.log", "w")
        logfile.write(logtext)
        logfile.close()


def raw_string(s):
    if isinstance(s, str):
        s = s.encode('string-escape')
    elif isinstance(s, unicode):
        s = s.encode('unicode-escape')
    return s


def merge_two_dicts(x, y):
    z = x.copy()  # start with x's keys and values
    z.update(y)  # modifies z with y's keys and values & returns None
    return z


def regex_from_paramstr(paramstr):
    raw_ps = raw_string(paramstr)
    pattern = r";.*" + raw_ps + r" (?P<" + raw_ps + r">.*)\n"
    return pattern


def regex_from_gcode_varname(variable_name):
    """
    generate regular expressions to extract variables that slic3r has noted in the gcode file
    eg <cooling tube>= r"; cooling_tube_length.?=.(?P<cooling_tube_length>-?\d*)"
    """
    varname = raw_string(variable_name)

    pattern = r";.*" + varname + r".?=.(?P<" + varname + r">-?\d*)\n"
    return pattern


def extract_params(tool, paramstr):
    out_dict = {}
    for param in SET_ITEMS:
        regex = regex_from_paramstr(param)

        try:
            matches = re.search(regex, paramstr, re.MULTILINE)
            if matches is not None:
                thisitem = str(matches.group(param)).strip()
                # lprint (str(tool)+":  "+str(param)+" = " + str(matches.group(param)), False)
                out_dict[param] = thisitem

        except Exception, e:
            print str(e)
            lprint("no matches for " + tool + ": regex" + regex)
            out_dict[param] = -1
            pass
    # print "returning out_dict for "+tool+" "+ pprint.pformat(out_dict)
    return out_dict


def get_dip_gcode(d, toolnumber):
    if toolnumber not in d.configured_tools:
        return ""
    insertion_distance = d.tool_settings[toolnumber]["insertion_distance"]
    insertion_speed = d.tool_settings[toolnumber]["insertion_speed"]
    extraction_speed = d.tool_settings[toolnumber]["extraction_speed"]
    material_name = d.tool_settings[toolnumber]["material_name"]
    material_type = d.tool_settings[toolnumber]["material_type"]
    toolchange_temp = d.tool_settings[toolnumber]["toolchange_temp"]
    insertion_pause = d.tool_settings[toolnumber]["insertion_pause"]
    removal_pause = d.tool_settings[toolnumber]["removal_pause"]
    beep_on_dip = d.tool_settings[toolnumber]["beep_on_dip"]


    downbeep = ""
    upbeep = ""
    if int(beep_on_dip) > 0:
        downbeep = DOWN_BEEP
        upbeep = UP_BEEP

    dip_gcode = ""

    dip_gcode += ";*****SKINNYDIP THREAD REDUCTION*****************\n"
    dip_gcode += "; Tool(" + toolnumber + "), " + material_type + "/" \
                 + material_name + "\n" + downbeep
    
    if float(insertion_distance) > 0 and float(insertion_speed) > 0:
        dip_gcode += "G1 E" + str(insertion_distance) + " F" + \
                     str(insertion_speed) + \
                     "  ;move stringy tip into melt zone\n"
    if int(insertion_pause) > 0:
        dip_gcode += "G4 P" + str(insertion_pause) + \
                     "        ;pause in melt zone\n"

    if float(insertion_distance) > 0 and float(extraction_speed) > 0:
        dip_gcode += upbeep + "G1 E-" + str(insertion_distance) + " F" + \
                     extraction_speed + \
                     "  ;extract clean tip from melt zone\n"
    if int(removal_pause) > 0:
        dip_gcode += "G4 P" + str(removal_pause) + \
                     "        ;pause in cool zone\n"
    dip_gcode += ";************************************************\n"

    return dip_gcode


def get_settings(d):
    """
    extract settings from comments in filament start gcode and populate
    d.utool_settings (unverified settings from user)
    """
    d.utool_settings = {}  # dict to store configuration for each tool
    config_strings = {}

    # Initialize tool settings to null settings
    for i in TOOL_LIST:
        d.utool_settings[i] = NULL_SETTINGS_DICT
    try:
        firstmatch = re.search(FIRST_TOOL_SETTINGS_REGEX,
                               d.gcode_str, re.MULTILINE)
        if firstmatch != None:
            first_tool = firstmatch.group('first_tool')
            config_strings[first_tool] = str(firstmatch.group('config_string'))
            d.configured_tools.append(str(first_tool).strip())
    except Exception, e:
        print "Firstmatch failed." + str(e)

    # search for text chunks containing both a tool number and an associated
    # configuration string.
    chunks = re.finditer(ASSOCIATE_TOOL_WITH_SETTINGS_REGEX,
                         d.gcode_str, re.MULTILINE)
    # create dict that links the tool number to its settings profile
    if chunks is not None:
        for chunkNum, chunk in enumerate(chunks, start=0):
            if chunk is not None:
                # grab tool number from regex
                toolname = str(chunk.group('previous_tool')).strip()
                config_string = chunk.group('parameters')
                lprint("ADDED data from chunk: " + str(chunkNum) + " previous_tool:" + toolname, False)
                config_strings[toolname] = config_string
                if toolname not in d.configured_tools:
                    d.configured_tools.append(toolname)
                    sortlist = sorted(d.configured_tools)
                    d.configured_tools= sortlist
                    lprint("Configured tools is now" + str(d.configured_tools), False)

    lprint("  finished scanning configuration strings.", False)
    lprint("  Configured extruders: " + str(d.configured_tools), )
    lprint(pprint.pformat(config_strings), False)
    lprint("  Extracting settings dictionaries from config strings", False)
    for tool in d.configured_tools:
        tool_param_dict = {}
        tool_param_dict = extract_params(tool, config_strings[tool])
        d.utool_settings[tool] = merge_two_dicts(d.utool_settings[tool], tool_param_dict)
        # tool_settings[tool] = tool_param_dict

    # look up print temperatures to add to settings dict
    lprint("Scanning for main print temperature configuration...", False)
    print_temps_dict = get_temperature_config(d)
    lprint("Print temps are: " + str(print_temps_dict), False)

    for j in d.configured_tools:
        d.utool_settings[j]["print_temp"] = print_temps_dict[j]

    lprint("Settings before validation:\n" + str(pprint.pformat(d.utool_settings, indent=4) + "\n"), False)


def index_dip_insertion_points(d):
    '''
     finds positions where insertions in the input file need to be
     made and indexes them
     dip_index is dict of pointers to locations in the file and the
     contents of those locations for further processing
     dip_positions is an ascending list of those locations used when
     building the output file. (faster than searching for 
     existence of keys)
    '''

    d.dip_index = {}
    d.dip_positions = []
    # look for regex associated with place where skinnydip is needed
    #matches = re.finditer(COOLING_MOVE_REGEX, d.gcode_str, re.MULTILINE)
    matches = re.finditer(INSERTIONS_REGEX, d.gcode_str, re.MULTILINE)
    for matchNum, match in enumerate(matches, start=1):
        dip_pos = match.start("dip_pos")
        line_number = d.line_lookup[dip_pos]
        new_tool = match.group("new_tool")
        new_tool_pos = match.start("new_tool")

        temp_pause_pos = match.start("temp_pause")
        if temp_pause_pos is not None:
            add_temp_pause(d, temp_pause_pos)

        filament_temp = match.group("filament_temp")
        if filament_temp is None:
            temp_restore_pos = match.start("temp_restore")

            if temp_restore_pos is not None:
                add_temp_restore(d, temp_restore_pos)

        try:
            previous_tool = d.tc_dict[new_tool_pos]["previous_tool"]
            bundle = {"previous_tool": previous_tool,
                      "new_tool": new_tool,
                      "new_tool_pos": new_tool_pos,
                      "line_number" : line_number,
                      "output_gcode": get_dip_gcode(d, previous_tool)
                      }
            d.dip_index[dip_pos] = bundle
            d.dip_positions.append(dip_pos)  # to speed up render process
            d.dip_lines.append(line_number)
        except Exception, e:
            print str(e)

    lprint("dip postitions:\n" + str(d.dip_positions), False)
    lprint("dip_index:\n" + pprint.pformat(d.dip_index), False)
    spos = d.dip_positions
    sposlen = len(d.dip_positions)
    diplen = len(d.dip_index.keys())
    lprint("dip positions has " + str(sposlen) + " elements:", False)
    lprint("\n" + pprint.pformat(spos) + "\n", False)
    lprint("  dip index has " + str(diplen) + " elements")
    lprint("\n" + pprint.pformat(sorted(d.dip_index)) + "\n", False)
    return 0


def get_temperature_config(d):
    '''
    Scan gcode file for line that lists the temperature settings
    for every extruder.  The regex should return each temperature value
    as its own capture group.
    '''
    temperaturedict = {}
    temps = re.search(TEMPERATURE_REGEX, d.gcode_str)
    i = 0
    if temps is not None:
        for tool in TOOL_LIST:
            # print "tool "+str(tool)
            temperaturedict[tool] = str(temps.groups()[i])
            i += 1
        lprint("temperature config result:" + str(temperaturedict), False)
    else:
        lprint("No temperature configuration data in file.  Was it sliced with a  MMU profile?", error=True)

    return temperaturedict


def add_temp_restore(d,position):

    tool_number = get_tool_from_filepos(d, position)
    print_temp = d.tool_settings[tool_number]['print_temp']
    lprint (str(tool_number) + " temperature " + str(print_temp) + "    restored at pos: " + str(position), False)
    line_number = d.line_lookup[position]
    tempbeep = ["", ""]
    if d.tool_settings[tool_number]["beep_on_temp"] > 0:
        tempbeep = TEMP_BEEP

    temper_change_gcode = "; +++++++++++++++++++++++++++++++++++++++++\n"
    temper_change_gcode += tempbeep[1]
    temper_change_gcode += "M104 S" + str(print_temp)
    temper_change_gcode += " ;***SKINNYDIP Restoring temperature for  " + \
                          tool_number + ": " + str(print_temp) + "\n"
    temper_change_gcode += "; +++++++++++++++++++++++++++++++++++++++++\n"

    temper_details = {'toolchange_number': 0,
                      'tool_pos': position,
                      'tool_number': tool_number,
                      'toolchange_temp': print_temp,
                      'output_gcode': temper_change_gcode,
                      'line_number' : line_number
                      }
    # toolchange number to toolchange pos index
    d.temper_positions.append(position)  # to speed up render process
    d.temper_index[position] = temper_details
    d.temper_lines.append(line_number)


def build_gcode_header(d):
    # assemble statistics for gcode header
    ts = time.ctime()
    bod = []
    bot = []
    ins = []
    for tool in d.configured_tools:
        if d.tool_settings[tool]["beep_on_dip"] > 0:
            bod.append(tool)
        if d.tool_settings[tool]["beep_on_temp"] > 0:
            bot.append(tool)
        length = d.tool_settings[tool]["insertion_distance"]
        ins.append(length)

    if len(bod) == 0:
        bod = "None"
    if len(bot) == 0:
        bot = "None"

    header = "; SKINNYDIP THREAD REDUCTION v" + VERSION + "\n"
    header += "; https://github.com/domesticatedviking/skinnydip\n"
    header += "; Postprocessing completed on " + str(ts)+"\n"
    sorted_tools = sorted(d.configured_tools)
    header += ";         Configured extruders: " + str(sorted_tools) + "\n"
    header += ";            Insertion lengths: " + str(ins) + "\n"
    header += ";       Total # of toolchanges: " + str(len(d.tc_dict.keys())) + "\n"
    header += ";                   Dips added: " + str(d.dips_inserted) + "\n"
    header += ";       Toolchange_temps added: " + str(d.temp_drops_inserted) + "\n"
    header += ";      Auto insertion distance: " + str(d.auto_insertion_distance) + "\n"

    header += ";   Tools beeping on skinnydip: " + str(bod) + "\n"
    header += "; Tools beeping on temp change: " + str(bod) + "\n"
    lprint(header, False)
    return header


def prepare_insertions(d):
    """
    Speed up output by creating a list of insertions that maps to the line numbers
    in the output file

    :param d:
    :return:
    """

    # merge and sort temperature and dip lists
    d.dips_inserted=len(d.dip_lines)
    d.temp_drops_inserted = len(d.temper_lines)
    all_insertion_lines = sorted(list(set(d.temper_lines + d.dip_lines)))

    # combine the dictionaries of insertion points for simpler code below.
    blended_dict = merge_two_dicts(d.temper_index, d.dip_index)


    d.final_insertion_list.append(None) #shifts location of output down by one line

    for line_number in range(0, d.linecount):
        if line_number in all_insertion_lines:
            charpos = d.linebreak_list[line_number]
            output_gcode = blended_dict[charpos]["output_gcode"]
            d.final_insertion_list.append(output_gcode.strip())
        else:
            d.final_insertion_list.append(None)
    #lprint ("final insertion list")
    #lprint(str(d.final_insertion_list))









def add_temp_pause(d, position):
    tool_number = get_tool_from_filepos(d, position)
    toolchange_temp = d.tool_settings[tool_number]['toolchange_temp']
    line_number = d.line_lookup[position]
    tempbeep = ["",""]
    if d.tool_settings[tool_number]["beep_on_temp"] > 0:
        tempbeep = TEMP_BEEP

    temper_change_gcode = "; *****************************************\n"
    temper_change_gcode += tempbeep[0]
    temper_change_gcode += "M109 R" + str(
        toolchange_temp) + " ;***SKINNYDIP Waiting for " + \
                          tool_number + " toolchange temp: "+str(toolchange_temp)+"\n" + tempbeep[1]
    temper_change_gcode += "; *****************************************\n"

    temper_details = {'toolchange_number': 0,
                      'tool_pos': position,
                      'tool_number': tool_number,
                      'toolchange_temp': toolchange_temp,
                      'output_gcode': temper_change_gcode,
                      'line_number': line_number
                      }

    # toolchange number to toolchange pos index
    d.temper_positions.append(position)  # to speed up render process
    d.temper_index[position] = temper_details
    d.temper_lines.append(line_number)

def index_temperature_change_positions(d):
    """
    d.gcode_str, d.tc_index, d.toolnumber_sequence, d.tool_settings
    """
    SEQ_SHIFT = 0
    #d.temper_index = {}   #don't erase work of other  functions!
    #d.temper_positions = []

    # scan for temperature change patterns
    matches = re.finditer(TOOLCHANGE_TEMP_REGEX, d.gcode_str)
    for matchNum, match in enumerate(matches, start=1):
        if match is not None:
            changepos = int(match.start('temp_start'))
            line_number = d.line_lookup[changepos]
            tool_number = get_tool_from_filepos(d, changepos)

            toolchange_temp = d.tool_settings[tool_number]['toolchange_temp']

            tempbeep = ["", ""]
            if d.tool_settings[tool_number]["beep_on_temp"] > 0:
                tempbeep = TEMP_BEEP

            temper_change_gcode = ""
            temper_change_gcode += tempbeep[0]
            temper_change_gcode += "M104 S" + str(toolchange_temp) + \
                               " ;***SKINNYDIP initiating " + str(tool_number) + " toolchange temperature.  Target: "+str(toolchange_temp)+"***\n"

            temper_details = {'toolchange_number': 0,
                          'tool_pos': changepos,
                          'tool_number': tool_number,
                          'toolchange_temp': toolchange_temp,
                          'output_gcode': temper_change_gcode,
                           'line_number': line_number,
                          }
            d.temper_positions.append(changepos)  # to speed up render process
            d.temper_positions=sorted(d.temper_positions) #required or some will be lost.
            d.temper_index[changepos] = temper_details
            d.temper_lines.append(line_number)

    temperlen = str(len(d.temper_index.keys()))
    lprint("  Temperature drop index has " + temperlen + " elements")
    lprint("\n" + pprint.pformat(d.temper_index) + "\n", False)
    return 0

def index_toolchanges(d):
    '''
    Indexes locations of tool changes in the gcode, and creates a dictionary
    that allows us to know what tool is currently active (the tool activated
    by the previous toolchange).

    d.tc_dict = {}  #indexes toolchanges with their predecessor tools by file position
                    eg: {30003:{"new_tool":'T1', "previous_tool" T2}, etc}
    d.tc_list = []  #lists file positions of toolchanges eg [1993,33335,33339]
    d.toolnumber_sequence = [] #the sequence of tools used in the gcode file eg ['T0','T1','T3']
    '''
    #
    d.tc_dict = {}
    d.tc_list = []
    d.toolnumber_sequence = []

    # lookup first tool
    # firstmatch = re.search(FIRST_TOOL_SETTINGS_REGEX,
    #                       gcode_str, re.MULTILINE)
    # first_tool = firstmatch.group('first_tool')
    # toolnumber_sequence.append(first_tool)  #gets picked up twice.
    # firstmatchpos = int(firstmatch.start('first_tool'))
    # prev_tool = first_tool.strip()
    prev_tool = None
    lprint("Scanning for toolchanges for retrieval of previous tool value by toolchange at position.", False)
    matches = re.finditer(TOOLCHANGE_REGEX, d.gcode_str, re.MULTILINE)
    if matches is not None:
        for matchNum, match in enumerate(matches, start=0):
            if match is not (None):
                new_tool_pos = (match.start('tool'))  # add 1 because of initial newline
                line_number = d.line_lookup[new_tool_pos]
                new_tool = str(match.group('tool')).strip()
                d.tc_dict[new_tool_pos] = {'new_tool': new_tool,
                                         'previous_tool': prev_tool,
                                           'line_number': line_number}
                prev_tool = new_tool
                d.tc_list.append(new_tool_pos)
                d.tc_lines.append(line_number)
                d.toolnumber_sequence.append(new_tool)
            else:
                lprint("No toolchanges found!")

    # final tool removal doesn't match the regular pattern.
    # There is also no toolchange lookup possible because there
    # is no actual toolchange here.  So we have to fake one.
    final = re.search(FINAL_TOOLCHANGE_REGEX, d.gcode_str)
    if final is not None:
        finalpos = int(final.start())
        # sanity check, line should contain M220 R
        if str(final.groups("final")[0]) != "M2":  # group
            lprint("Error with final toolchange.  Unexpected value" + \
                        str(final.groups("final")))


        else:
            d.tc_dict[finalpos] = {"new_tool": "end",
                                 "previous_tool": prev_tool}

    tc_length = len(d.tc_dict.keys())
    ts_length = len(d.toolnumber_sequence)
    lprint("  Toolchange index has " + str(tc_length) + " elements")
    lprint(pprint.pformat(d.tc_dict), False)
    lprint("Tool sequence has " + str(ts_length) + " elements:" + \
           pprint.pformat(d.toolnumber_sequence), False)
    return 0


def get_nearest(poslist, mypos):
    """

    """
    #if mypos > poslist[-1] or mypos < poslist[0]:
    #    return None
    pos = bisect_left(poslist, mypos)
    if pos == 0:
        return poslist[0]
    if pos == len(poslist):
        return poslist[-1]
    before = poslist[pos - 1]
    after = poslist[pos]
    if after - mypos < mypos - before:
        return after
    else:
        return before


def get_tool_from_filepos(d, filepos):
    """
    Optimized search that scans for nearest tool location based on current position in the file
    If the nearest location is from a higher position, retrieves the next lowest position and returns it instead.

    """
    scanlist=d.tc_list
    nearest_toolchange = get_nearest(scanlist, filepos)
    if nearest_toolchange > filepos:   # toolchange happened after the position in the file (wrong one!)
        nearest_index = d.tc_list.index(nearest_toolchange)  #  search for the index's position in the list
        nearest_toolchange= d.tc_list[nearest_index-1]
    return d.tc_dict[nearest_toolchange]['new_tool']

def build_output_lines(d):
    #d.final_insertion_list
    gcode_header = build_gcode_header(d).splitlines()
    for line in gcode_header:
        d.output_lines.append(line+"\n")

    for linenum in xrange(d.linecount):
        orgline = d.gcode_lines[linenum]
        #print "linenum =" + str(linenum)
        #print "original line =" + str(orgline)
        insline = d.final_insertion_list[linenum]
        #print "inserted line=" +str(insline)


        if insline is not None:
            for subline in insline.splitlines():
                d.output_lines.append(subline+"\n")
        d.output_lines.append(orgline)
    lprint(d.output_lines, False)




def build_output(d):
    d.dips_inserted = 0
    d.dips_ignored = 0
    d.temp_drops_inserted = 0
    d.temp_drops_ignored = 0
    d.out = ""
    d.sort_indexes()
    len_chars = len(d.gcode_str)
    current_dip_insertion = 0
    current_temp_insertion = 0
    i = 0
    d.build_start_time = datetime.now()
    dippos_len=len(d.dip_positions)
    temperpos_len=len(d.temper_positions)
    progress = 0
    progress_increment = len_chars/100
    updater = 0
    oldprogressbars = 0




    while (i < len_chars):

        dipmatch = False

        # check if current pos in file is indexed as an insertion point.
        if current_dip_insertion < dippos_len:
            dipspot = (d.dip_positions[current_dip_insertion])
            if i == dipspot:
                dipmatch = True
        else:
            dipmatch = False


        if dipmatch:
            # get the stored toolchange position from the dip index
            new_tool_pos = d.dip_index[i]["new_tool_pos"]
            # use that position to look up the tool that will be active during the dip
            previous_tool = d.tc_dict[new_tool_pos]["previous_tool"]
            # lprint(str(tc_dict[new_tool_pos]))
            # lprint("Current tool is" "'" + str(previous_tool) + "'")
            if previous_tool in d.configured_tools:
                dipinserted_text = get_dip_gcode(d, previous_tool)
                lprint(
                    "DIP GCODE for " + str(previous_tool) + " #" + str(current_dip_insertion) +
                    "\n " + dipinserted_text, False)
                dipaddtext = dipinserted_text
                d.out += dipaddtext + str(d.gcode_str[i])
                i += 1
                current_dip_insertion += 1
                d.dips_inserted += 1
            else:
                lprint("(" + str(previous_tool) + ") Suppressed Dip # " + str(current_dip_insertion) + \
                       " at pos " + str(i), False)
                d.out += str(d.gcode_str[i])
                i += 1
                current_dip_insertion += 1
                d.dips_ignored += 1


        tempermatch = False
        if current_temp_insertion < temperpos_len:
            tempermatch = (i == d.temper_positions[current_temp_insertion])
        else:
            tempermatch = False

        if tempermatch:

            # retrieve the tool position from the temperature index
            tool = d.temper_index[i]['tool_number']
            if tool in d.configured_tools:
                temper_change_gcode = d.temper_index[i]['temper_change_gcode']
                inserted_text = temper_change_gcode
                d.out += inserted_text
                d.out += str(d.gcode_str[i])
                i += 1
                current_temp_insertion += 1
                d.temp_drops_inserted += 1
            else:
                print "(" + str(tool) + ") Suppressed TEMPDROP " + str(current_temp_insertion) + " at pos " + str(i)
                d.out += str(d.gcode_str[i])
                i += 1
                current_temp_insertion += 1
                d.temp_drops_ignored += 1

        if not (dipmatch) and not (tempermatch):
            d.out += str(d.gcode_str[i])
            i += 1

        if updater == progress_increment:
            print str(int((float(i)/float(len_chars))*100))
            updater = 0
        updater += 1
        #if progressbars != oldprogressbars:
        #    print str(progressbars)
        #    oldprogressbars = progressbars

    # assemble statistics for gcode header
    ts = time.gmtime()
    bod = []
    bot = []
    ins = []
    for tool in d.configured_tools:
        if d.tool_settings[tool]["beep_on_dip"] > 0:
            bod.append(tool)
        if d.tool_settings[tool]["beep_on_temp"] > 0:
            bot.append(tool)
        length = d.tool_settings[tool]["insertion_distance"]
        ins.append(length)

    if len(bod) == 0:
        bod = "None"
    if len(bot) == 0:
        bot = "None"

    header = "; SKINNYDIP THREAD REDUCTION v" + VERSION + "\n"
    header += "; https://github.com/domesticatedviking/skinnydip\n"
    header += "; Postprocessing completed on " + (time.strftime("%x %X", ts)) + "(UTC)\n; \n"
    sorted_tools = sorted(d.configured_tools)
    header += ";   Configured extruders: " + str(sorted_tools) + "\n"
    header += ";      Insertion lengths: " + str(ins) +"\n"
    header += "; Total # of toolchanges: " + str(len(d.tc_dict.keys())) + "\n"
    header += ";             Dips added: " + str(d.dips_inserted) + "              Dips ignored: " +\
              str(d.dips_ignored) + "\n"
    header += "; Toolchange_temps added: " + str(d.temp_drops_inserted) + "  Toolchange temps ignored: " + \
              str(d.temp_drops_ignored) + "\n"
    header += ";Auto insertion distance: " + str(d.auto_insertion_distance) +"\n"

    header += ";   Tools beeping on skinnydip: "+str(bod) + "\n"
    header += "; Tools beeping on temp change: " + str(bod) +"\n"
    d.out = header + d.out
    lprint(header, False)
    return 0


def clean_settings(d):
    dirty = d.utool_settings.copy()  #save a copy to clean in place
    for tool in d.configured_tools:
        lprint("  Verifying safe settings for tool: " + str(tool), False)
        for setting in SAFE_RANGE.keys():
            text_value = False
            try:
                v = dirty[tool][setting]
            except:
                v = None
            lprint("    " + str(tool) + ": " + setting + " = " + str(v), False)
            low = SAFE_RANGE[setting][0]
            high = SAFE_RANGE[setting][1]
            try:
                other_values = SAFE_RANGE[setting][2]
            except:
                other_values = []

            if v is not None:
                if str(v).upper() in other_values:
                    text_value=True

            try:
                if float(v) < float(low):
                    lprint("  Minimum setting " + setting + " for " + \
                           tool + " enforced: " + str(low))
                    dirty[tool][setting] = str(low)

                elif float(v) > float(high):
                    lprint("  Maximum setting " + setting + " for " + \
                           tool + " enforced: " + str(high))
                    dirty[tool][setting] = str(high)
            except:
                pass


            if dirty[tool]["toolchange_temp"] > 0:
                if float(dirty[tool]['toolchange_temp']) < float(TOOLCHANGE_TEMP_SAFE_RANGE[0]):
                    lprint("  Minimum setting " + setting + " for " + \
                           tool + " enforced: " + str(TOOLCHANGE_TEMP_SAFE_RANGE[0]))
                    dirty[tool]['toolchange_temp'] = TOOLCHANGE_TEMP_SAFE_RANGE[0]

                if float(dirty[tool]['toolchange_temp']) > TOOLCHANGE_TEMP_SAFE_RANGE[1]:
                    lprint("  Maximum setting " + setting + " for " + \
                           tool + " enforced: " + str(TOOLCHANGE_TEMP_SAFE_RANGE[1]))
                    dirty[tool]['toolchange_temp'] = SAFE_RANGE[setting][1]
            else:
                lprint("Value was missing for : " + str(tool) + "-" + str(setting))

    d.tool_settings = dirty #save clean values
    d.apply_automatic_values()
    return 0


def get_extruder_settings(d):
    for var in VARS_FROM_SLIC3R_GCODE:
        pattern = regex_from_gcode_varname(var)

        result = re.search(pattern, d.gcode_str)
        if result is not None:
           value = str(result.group(var))
           d.gcode_vars[var] = value
           lprint("from gcode: "+str(var)+" = "+str(value))

        else: lprint("WARNING: "+ str(var) + " not found in gcode file.")
    return


def lprint(message, display=True, error=False):
    global logtext
    logtext += str((message)) + "\n"
    if error:
        raise CustomError(message)
    if display:
        print message

def auto_calculate_insertion_length(d):
    tube_pos = float(d.gcode_vars['cooling_tube_retraction'])
    tube_length = float(d.gcode_vars['cooling_tube_length'])
    insertion_distance = tube_pos + (0.5 * tube_length) - 1.5
    d.auto_insertion_distance = insertion_distance
    lprint ("Based on the data in this gcode file, your suggested insertion_length is %.1f" % insertion_distance)
    return insertion_distance

def index_linebreaks(d):
    d.linebreak_list = []
    d.line_lookup = {}
    linebreaks = re.finditer(LINEBREAKS_REGEX, d.gcode_str, re.MULTILINE)
    d.linecount = 0
    for linebreakNum, linebreak in enumerate(linebreaks, start=0):
        pos = linebreak.start("linebreak")
        d.linebreak_list.append(pos+1) #we want to target the beginnings of lines
        d.line_lookup[pos+1] = linebreakNum
        d.linecount += 1
    print "  lines in file: " + str(d.linecount)
    #lprint(str(len(d.linebreak_list))+" linebreaks were found:")
    #lprint(str(d.linebreak_list))
    #lprint(str(len(d.linebreak_list)) + " elements in line lookup dict:")
    #lprint(str(d.line_lookup))


def main(target_file=None):
    lprint("Skinnydip MMU2 String Eliminator v" + VERSION)
    d = SetupData(target_file)
    #try:
    d.open_target_file()
    d.check_target_file()
    d.init_log_file("skinnydip.log")
    lprint("Looking up extruder settings")
    get_extruder_settings(d)
    auto_calculate_insertion_length(d)
    lprint("Indexing linebreaks")
    index_linebreaks(d)
    lprint("Indexing toolchanges...")
    index_toolchanges(d)
    lprint("Scanning gcode for configuration parameters...")
    get_settings(d)
    lprint("Validating User Settings...")
    clean_settings(d)
    lprint("Searching for skinnydip, wait for temperature, and temperature restore gcode injection locations...")
    index_dip_insertion_points(d)
    lprint("Searching for initial temperature change gcode injection locations...")
    index_temperature_change_positions(d)
    lprint("Compiling final insertion list...")
    prepare_insertions(d)
    d.close_target_file()
    lprint("Preparing to build output file")
    d.open_target_file_lines()
    build_output_lines(d)
    d.write_output_file_lines()
    d.write_log_file()
    lprint("Post processing complete.  Exiting...")
    exit(0)
    """
    except Exception, e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        d.write_log_file()
        d.close_target_file()
        exit(-1)
        raise
    """

if __name__ == "__main__":
    target_file = None
    try:
        if TEST_FILE is not None:
            shutil.copyfile(RESOURCE_PATH + TEST_FILE, PROJECT_PATH + TEST_FILE)
            target_file = PROJECT_PATH + TEST_FILE
    except:
        pass
    main(target_file)
