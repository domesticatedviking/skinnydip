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

#  MODULES  ************************************************
import argparse
import getopt
from bisect import bisect_left
import re
import pprint
import os
import time
import shutil
import sys


#  CONSTANTS ************************************************
VERSION = "1.0.3 beta"
TEST_FILE = ""
RESOURCE_PATH = "/home/erik/PycharmProjects/skinnydip/testobjects/"
PROJECT_PATH = "/home/erik/PycharmProjects/skinnydip/"

TOOL_LIST = ["T0", "T1", "T2", "T3", "T4"]

#distance in mm to fine tune automatic insertion distance
AUTO_INSERTION_DISTANCE_TWEAK = -2

# settings to initialize all tools
NULL_SETTINGS_DICT = {
    "insertion_distance": "auto",
    "material_type": "N/A",
    "material_name": "not configured",
    "toolchange_temp": "OFF",
    "print_temp": -1,
    "insertion_speed": 0,
    "extraction_speed": 0,
    "insertion_pause": 0,
    "removal_pause": 0,
    "beep_on_dip": 0,
    "beep_on_temp": 0,
}

# [lower limit, upper limit, [accepted values], default if no value]
SAFE_RANGE = {
    "insertion_speed": [300, 10000, [], 2000],
    "extraction_speed": [300, 10000, [], 4000],
    "insertion_pause": [0, 20000, [None, ], 0],
    "insertion_distance": [0, 60, ["AUTO", None], "AUTO"],
    "removal_pause": [0, 20000, [None, ], 0],
    "print_temp": [150, 295, [], "error"],
    "toolchange_temp": [150, 295, [0, -1, "0", "-1", "OFF"], "OFF"],
    "beep_on_dip": [0, 1, ["OFF", "ON"], "OFF"],
    "beep_on_temp": [0, 1, ["OFF", "ON"], "OFF"],
}

SET_ITEMS = NULL_SETTINGS_DICT.keys()
VARS_FROM_SLIC3R_GCODE = ['cooling_tube_length', 'cooling_tube_retraction',
                          'extra_loading_move', 'parking_pos_retraction']
# Alert Tones
DOWN_BEEP = "M300 S5742 P195 ;downbeep\nM300 S3830 P95  ;downbeep\n" + \
            "M300 S1912 P95  ;downbeep\n"
UP_BEEP = "M300 S1912 P95  ;upbeep\nM300 S3830 P95  ;upbeep\n" + \
          "M300 S5742 P195 ;upbeep\n"

# REGULAR EXPRESSIONS*********************************************************
INSERTIONS_REGEX = r"(?P<temp_pause>G1 E-.*\n)((G1 E-|M73).*\n){2,7}" + \
                   r"(M104 S(?P<filament_temp>.*)\n)?(?P<temp_restore>" + \
                   r"G1 [^E].*\n)(?:.*\n){1,20}(?P<dip_pos>G1 E-).*\n" + \
                   r"(.*\n){1,5}(?P<new_tool>T\d)"

TEMP_BEEP = ["M300 S3038 P155 ;temp_beep\n", "M300 S2550 P75 ;temp_beep\n"]
CONFIGSTRING_REGEX = r"(SKINNYDIP CONFIGURATION START.?)(?P<configstring>.*)"
WAIT_FOR_TEMP_REGEX = r"(?P<wait_for_temp>^G1 E-\d\d.*\n)(^G1 E-.*$\n)" + \
                      r"{1,30}M104 S.*"
TOOLCHANGE_TEMP_REGEX = r"M220 B.*\nM220 S(?P<speed_override>\d.*)\n" + \
                        r"(M.*\n)?(?P<temp_start>; CP TOOLCHANGE UNLOAD)"
SETTINGS_REGEX = r"(?P<previous_tool>^T[01234].*$)(?P<otherstuff>(.*\n)" + \
                 r"{10,250}?); SKINNYDIP CONFIGURATION START.*\n" + \
                 r"(?P<parameters>(; .*\n){1,11});.?SKINNYDIP " + \
                 r"CONFIGURATION END"
COOLING_MOVE_REGEX = r"(?P<dip_pos>G1 E-).*\n(.*\n){1,5}(?P<new_tool>T\d)"
TOOLCHANGE_REGEX = r"(?P<tool>^T[01234]$)"
FINAL_TOOLCHANGE_REGEX = r"G1 E.*\nG1.*\nG4 S0\n(?P<final>M2)20 R"  # ?M73
TEMPERATURE_REGEX = regex = r"; temperature = (...),(...),(...),(...),(...)"
FIRST_TOOL_SETTINGS_REGEX = r"\n(?P<first_tool>T[0-4])\nM.*\n;.*(SKINNYDIP " + \
                            r"CONFIGURATION START)\n(?P<config_string>" + \
                            r"(;.*\n)*)"
LINEBREAKS_REGEX = r"(?P<linebreak>\n)"

# GLOBAL VARS
logtext = ""


# CLASS DEFINITIONS **********************************************************
class CustomError(Exception):
    """
    Generic custom error handler
    """
    pass



class FileInfo():
    """
    Object for handling data related to the manipulation of text files.
    Has separate functions for manipulating files by char and by line.
    """

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

        self.skinnydip_script_absolute = os.path.abspath(__file__)
        self.skinnydip_script_dir = (os.path.dirname(self.skinnydip_script_absolute)).rstrip(os.sep)
        self.log_file_name = str(os.path.join(self.skinnydip_script_dir, "skinnydip.log"))

        if self.target_file is not None:
            self.file_to_process = target_file
            self.keep_original = False
        else:
            self.parser = argparse.ArgumentParser()
            self.parser.add_argument("myFile", nargs="+")  # "+" is for filenames with spaces
            self.parser.add_argument("--k", "--keep", action='store_true',
                                     help="keep copy of original file")
            self.args = self.parser.parse_args()

            self.keep_original = self.args.k
            self.myFile = ' '.join(self.args.myFile)  # handle filenames with spaces
            self.file_to_process = self.args.myFile

            self.inputfile_realpath = os.path.realpath(self.myFile)
            self.file_to_process = self.inputfile_realpath
            self.inputfile_dir = os.path.dirname(self.inputfile_realpath)
            self.inputfile_bn = os.path.basename(self.myFile)

        if self.file_to_process is not None:
            self.inputfilename = os.path.splitext(self.inputfile_bn)[0]
            self.inputextension = os.path.splitext(self.inputfile_bn)[1]
            self.inputfull = self.inputfilename + self.inputextension
            self.inputfullpath = os.path.join(self.inputfile_dir, self.inputfull)


            self.outputfilename = self.inputfilename + "_skinnydip" + self.inputextension
            self.outputfilenamefull = os.path.join(self.inputfile_dir, self.outputfilename)

            self.bakfilename = (self.inputfilename) + "_original" + (self.inputextension)
            self.bakfilefullpath = os.path.join(self.inputfile_dir, self.bakfilename)


            lprint('File received for processing was {}'.format(self.file_to_process))
        else:
            lprint('No file received as an argument')


    def open_file_lines(self):
        self.f = open(self.file_to_process)
        self.lines = self.f.readlines()  # was .f.read()

    def open_file(self):
        self.f = open(self.file_to_process)
        self.text = str(self.f.read())

    def close_file(self):
        self.f.close()
        del self.text
        self.text = ""

    def close_file_lines(self):
        self.f.close()
        del self.lines
        self.lines = []

    def write_output_file(self, contents):
        lprint("writing output to temporary file: " + self.outputfilenamefull)
        self.outfile = open(self.outputfilenamefull, 'w')
        self.outfile.write(contents)
        self.outfile.close()
        self.close_file()
        if self.keep_original:
            lprint("renaming original file as " + self.bakfilefullpath)
            os.rename(self.inputfullpath, self.bakfilefullpath)
        else:
            lprint("deleting original file: " + self.inputfull)
            os.remove(self.inputfullpath)
        lprint("moving post processed output to " + self.inputfullpath)
        os.rename(self.outputfilenamefull, self.inputfullpath)

    def write_output_file_lines(self, contents):
        lprint("writing output to temporary file: " + self.outputfilenamefull)
        self.outfile = open(self.outputfilenamefull, 'w')
        self.outfile.writelines(contents)
        self.outfile.close()
        self.close_file_lines()
        if self.keep_original:
            lprint("renaming original file as " + self.bakfilefullpath)
            os.rename(self.inputfullpath, self.bakfilefullpath)
        else:
            lprint("deleting original file: " + self.inputfullpath)
            os.remove(self.inputfullpath)
        lprint("moving post processed output to " + self.inputfullpath)
        os.rename(self.outputfilenamefull, self.inputfullpath)


class SetupData():
    """
    Data storage and configuration object.  Mainly transports data between functions
    """

    def __init__(self, target_file):
        self.scriptpath =  os.path.abspath(__file__)
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
        self.fileinfo = FileInfo(target_file)
        self.output_lines = []
        self.notices = []
        self.log_file_name = self.fileinfo.log_file_name

    def sort_indexes(self):
        # self.temper_index = sorted(self.temper_index)
        # self.dip_index = sorted(self.dip_index)
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
        lprint("Writing log file at " + str(self.fileinfo.log_file_name) + "\n")
        logfile = open(self.fileinfo.log_file_name, "w")
        logfile.write(logtext)
        logfile.close()


# GENERIC UTILITY FUNCTIONS **************************************************
def raw_string(s):
    """
    ensures that slashes are not read as escape characters.  Important when
    forming regular expressions from strings
    :param : generic string to convert to regex
    :return: raw string
    """
    if isinstance(s, str):
        s = s.encode('string-escape')
    elif isinstance(s, unicode):
        s = s.encode('unicode-escape')
    return s


def merge_two_dicts(x, y):
    z = x.copy()
    z.update(y)
    return z


def best_type(thisitem):
    """
    Takes an input of unknown type, tests it and returns the most logical type for that item
    :param thisitem: int, float, string, or string encoded int or float.
    :return: a string, unless the item is more logically represented as an integer or a float
    """
    try:
        val = int(thisitem)
        whattype = "integer"
    except ValueError:
        try:
            val = float(thisitem)
            whattype = "float"
        except ValueError:
            val = str(thisitem)
            whattype = "string"
    return val, whattype


def get_nearest(poslist, mypos):
    """
    Utility function to find the number closest to a an item in a list of numbers
    :param: poslist: a list of integers
    :param: mypos: an integer
    :returns  an integer
    """
    # if mypos > poslist[-1] or mypos < poslist[0]:
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


def lprint(message, display=True, error=False):
    """
    Very simple logger and error reporter.  Requires global string variable logtext.
    :param message: String indicating information or error
    :param display: Outputs the information to the console in addition to logging it
    :param error: After logging the information, raises an error that displays the message
    :return:
    """
    global logtext
    logtext += str((message)) + "\n"
    if error:
        raise CustomError(message)
    if display:
        print message


# APPLICATION SPECIFIC UTILITY FUNCTIONS**************************************
def regex_from_paramstr(paramstr):
    """
    Secondary function that accepts a variable name and forms a regular expression to scan
    for that variable in configuration text
    :param paramstr: string - variable name
    :return: regular expression as raw string
    """
    raw_ps = raw_string(paramstr)
    pattern = r";.*" + raw_ps + r" (?P<" + raw_ps + r">.*)\n"
    return pattern


def regex_from_gcode_varname(variable_name):
    """
    Secondary function that generate regular expressions to extract variables that slic3r has
    noted in the gcode file
    eg <cooling tube>= r"; cooling_tube_length.?=.(?P<cooling_tube_length>-?\d*)"
    """
    varname = raw_string(variable_name)

    pattern = r";.*" + varname + r".?=.(?P<" + varname + r">-?\d*)\n"
    return pattern


def extract_params(tool, paramstr):
    """
    Secondary function to extract user's configuration parameters from the comments left in
    filament start gcode comments.
    :param tool:  Tool name ([T0..T4])
    :param paramstr: String containing all of the settings for this tool.
    :return: dictionary of values for all parameters listed in SET_ITEMS
    """
    out_dict = {}
    for param in SET_ITEMS:
        regex = regex_from_paramstr(param)

        try:
            matches = re.search(regex, paramstr, re.MULTILINE)
            if matches is not None:
                thisitem = str(matches.group(param)).strip()
                thisitem, besttype = best_type(thisitem)
                out_dict[param] = thisitem

        except Exception, e:
            print str(e)
            lprint("no matches for " + tool + ": regex" + regex)
            out_dict[param] = -1
            pass
    return out_dict


def get_tool_from_filepos(d, filepos):
    """
    Optimized search that scans for nearest tool location based on current position in the file
    If the nearest location is greater than filepos, retrieves the next lowest position and returns it instead.
    :param d: SetupData object
    :param filepos: int: character position in input file
    :return: string- toolnumber [T0..T4]
    """
    scanlist = d.tc_list
    nearest_toolchange = get_nearest(scanlist, filepos)
    if nearest_toolchange > filepos:  # toolchange happened after the position in the file (wrong one!)
        nearest_index = d.tc_list.index(nearest_toolchange)  # search for the index's position in the list
        nearest_toolchange = d.tc_list[nearest_index - 1]
    return d.tc_dict[nearest_toolchange]['new_tool']


# OUTPUT FUNCTIONS ***********************************************************
def generate_temp_restore(d, position):
    """
    Slicer is inconsistent about setting tool temperatures when
    beginning toolchanges (it may not insert an M104 if the temp is same
    as that used by the previous tool.   This function creates gcode strings
    to ensure that M104's are inserted so that the printer returns from any
    toolchange temperatures that have been set.
    :param d: SetupData object
    :param position:  int: character position in a file
    :return:none
    """
    tool_number = get_tool_from_filepos(d, position)
    print_temp = d.tool_settings[tool_number]['print_temp']
    if str(print_temp).upper() in ["ERROR", "OFF", "0", "NONE", "-1"]:
        lprint("FATAL ERROR:  Restore temperature out of range!", error=True)
    lprint(str(tool_number) + " temperature " + str(print_temp) + "    restored at pos: " + str(position), False)
    line_number = d.line_lookup[position]
    tempbeep = ["", ""]
    if str(d.tool_settings[tool_number]["beep_on_temp"]).upper() in ["ON", "1"]:
        tempbeep = TEMP_BEEP

    temper_change_gcode = "; +++++++++++++++++++++++++++++++++++++++++\n"
    temper_change_gcode += tempbeep[1]
    temper_change_gcode += "M104 S" + str(print_temp)
    temper_change_gcode += " ;***SKINNYDIP Restoring temperature for  " + \
                           str(tool_number) + ": " + str(print_temp) + "\n"
    temper_change_gcode += "; +++++++++++++++++++++++++++++++++++++++++\n"

    temper_details = {'toolchange_number': 0,
                      'tool_pos': position,
                      'tool_number': tool_number,
                      'toolchange_temp': print_temp,
                      'output_gcode': temper_change_gcode,
                      'line_number': line_number
                      }
    # toolchange number to toolchange pos index
    d.temper_positions.append(position)  # to speed up render process
    d.temper_index[position] = temper_details
    d.temper_lines.append(line_number)


def generate_dip_gcode(d, toolnumber):
    """
    Secondary function to generate a "skinnydip" operation.
    :param d: SetupData object
    :param toolnumber: [T0..T4]
    :return: a string of gcode to be inserted in the output file
    """
    if toolnumber not in d.configured_tools:
        return ""
    insertion_distance = d.tool_settings[toolnumber]["insertion_distance"]
    insertion_speed = d.tool_settings[toolnumber]["insertion_speed"]
    extraction_speed = d.tool_settings[toolnumber]["extraction_speed"]
    material_name = d.tool_settings[toolnumber]["material_name"]
    material_type = d.tool_settings[toolnumber]["material_type"]
    insertion_pause = d.tool_settings[toolnumber]["insertion_pause"]
    removal_pause = d.tool_settings[toolnumber]["removal_pause"]
    beep_on_dip = d.tool_settings[toolnumber]["beep_on_dip"]
    downbeep = ""
    upbeep = ""
    if str(beep_on_dip).upper() in ["ON", "1"]:
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
    if float(insertion_pause) > 0:
        dip_gcode += "G4 P" + str(insertion_pause) + \
                     "        ;pause in melt zone\n"
    if float(insertion_distance) > 0 and float(extraction_speed) > 0:
        dip_gcode += upbeep + "G1 E-" + str(insertion_distance) + " F" + \
                     str(extraction_speed) + \
                     "  ;extract clean tip from melt zone\n"
    if int(removal_pause) > 0:
        dip_gcode += "G4 P" + str(removal_pause) + \
                     "        ;pause in cool zone\n"
    dip_gcode += ";************************************************\n"
    return dip_gcode


def generate_gcode_header(d):
    """
    Outputs configuration data as comments to be placed at the beginning
    of the post processed gcode file.
    :param d: SetupData object
    :return: string of gcode
    """
    # assemble statistics for gcode header
    ts = time.ctime()
    bod = []
    bot = []
    ins = []
    tct = []
    for tool in d.configured_tools:
        if str(d.tool_settings[tool]["beep_on_dip"]).upper() in ["ON", "1"]:
            bod.append(tool)
        if str(d.tool_settings[tool]["beep_on_temp"]).upper() in ["ON", "1"]:
            bot.append(tool)
        tct.append(d.tool_settings[tool]["toolchange_temp"])
        length = d.tool_settings[tool]["insertion_distance"]
        ins.append(length)

    if len(bod) == 0:
        bod = "None"
    if len(bot) == 0:
        bot = "None"



    header = "; SKINNYDIP THREAD REDUCTION v" + VERSION + "\n"
    header += "; https://github.com/domesticatedviking/skinnydip\n"
    header += "; Postprocessing completed on " + str(ts) + "\n"
    header += ";               File Processed:" + str(d.fileinfo.inputfile_realpath) + "\n"
    header += "; Note that editing the values below will have no effect on your\n"
    header += "; Skinnydip settings.  To change parameters you must reslice.\n\n"
    sorted_tools = sorted(d.configured_tools)
    header += ";         Configured extruders: " + str(sorted_tools) + "\n"
    header += ";             Toolchange temps: " + str(tct) + "\n"
    header += ";            Insertion lengths: " + str(ins) + "\n"
    header += ";      Auto insertion distance: " + str(d.auto_insertion_distance) + "\n"
    header += ";       Total # of toolchanges: " + str(len(d.tc_dict.keys())) + "\n"
    header += ";                   Dips added: " + str(d.dips_inserted) + "\n"
    header += ";       Toolchange temps added: " + str(d.temp_drops_inserted) + "\n"
    header += ";   Tools beeping on skinnydip: " + str(bod) + "\n"
    header += "; Tools beeping on temp change: " + str(bot) + "\n\n"
    if len(d.notices) > 0:
        header += "; SOME PARAMETERS WERE OUT OF SAFE RANGES AND WERE CORRECTED!\n"
        for notice in d.notices:
            header += "; " + str(notice)

    lprint(header, False)
    return header


def generate_wait_for_temp(d, position):
    """
    creates gcode string that inserts a M109 R command just prior to filament extraction on toolchange.
    This causes the printer to stop and wait for the specified toolchange temperature.  Cooler
    temperatures are associated with smaller and more uniform filament tips.
    :param d: SetupData object
    :param position: int: character position in input file
    :return: None - stores gcode string
    """
    tool_number = get_tool_from_filepos(d, position)
    toolchange_temp = d.tool_settings[tool_number]['toolchange_temp']
    line_number = d.line_lookup[position]
    tempbeep = ["", ""]
    if str(d.tool_settings[tool_number]["beep_on_temp"]).upper() in ["ON", "1"]:
        tempbeep = TEMP_BEEP

    temper_change_gcode = "; *****************************************\n"
    temper_change_gcode += tempbeep[0]
    temper_change_gcode += "M109 R" + str(
        toolchange_temp) + " ;***SKINNYDIP Waiting for " + \
                           tool_number + " toolchange temp: " + str(toolchange_temp) + "\n" + tempbeep[1]
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


def prepare_insertions(d):
    """
    Creates a list with length equal to the number of lines in the input file and populates
    the list with lines of text which will be inserted at that line in the file.
    The main purpose of this step is to speed up the output of the final file
    :param d: SetupData object
    :return: None
    """


    # merge and sort temperature and dip lists
    d.dips_inserted = len(d.dip_lines)
    d.temp_drops_inserted = len(d.temper_lines)
    if d.temp_drops_inserted == 0:
        all_insertion_lines = d.dip_lines
        blended_dict = d.dip_index
    elif d.dips_inserted == 0:
        all_insertion_lines = d.temper_lines
        blended_dict = d.temper_index
    elif d.dips_inserted == 0 and d.temp_drops_inserted == 0:
        lprint ("ERROR: No insertions to process!", error= True)
    else:
        all_insertion_lines = sorted(list(set(d.temper_lines + d.dip_lines)))
        # combine the dictionaries of insertion points
        blended_dict = merge_two_dicts(d.temper_index, d.dip_index)

    # shift location of output down by one line to ensure it maps to the right line of output code
    d.final_insertion_list.append(None)  # important!
    for line_number in range(0, d.linecount):
        if line_number in all_insertion_lines:
            charpos = d.linebreak_list[line_number]
            output_gcode = blended_dict[charpos]["output_gcode"]
            d.final_insertion_list.append(output_gcode.strip())
        else:
            d.final_insertion_list.append(None)


def assemble_final_output(d):
    """
    Inserts all of the pre-sorted and indexed positions into the original file
    Final compilation of the lines of text for the output file.
    :param d: SetupData
    :return: none
    """
    gcode_header = generate_gcode_header(d).splitlines()
    for line in gcode_header:
        d.output_lines.append(line + "\n")

    for linenum in xrange(d.linecount):
        orgline = d.gcode_lines[linenum]
        insline = d.final_insertion_list[linenum]

        if insline is not None:
            for subline in insline.splitlines():
                d.output_lines.append(subline + "\n")
        d.output_lines.append(orgline)
    lprint(d.output_lines, False)


# ANALYSIS FUNCTIONS *********************************************************
def index_linebreaks(d):
    """
    stores a list of all the newline characters in the input.  This became necessary
    since the input side of the program was done using character-level indexing, but
    this proved to be much too slow on the output side.
    :param d:
    :return:
    """
    d.linebreak_list = []
    d.line_lookup = {}
    linebreaks = re.finditer(LINEBREAKS_REGEX, d.gcode_str, re.MULTILINE)
    d.linecount = 0
    for linebreakNum, linebreak in enumerate(linebreaks, start=0):
        pos = linebreak.start("linebreak")
        d.linebreak_list.append(pos + 1)  # we want to target the beginnings of lines
        d.line_lookup[pos + 1] = linebreakNum
        d.linecount += 1
    print "  lines in file: " + str(d.linecount)


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
    d.tc_dict = {}
    d.tc_list = []
    d.toolnumber_sequence = []
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


def clean_settings(d):
    """
    Sanitize user inputs scanned in from gcode comments.
    Correct inputs that fall outside of SAFE_RANGE values
    :param d: SetupData
    :return: None
    """
    dirty = d.utool_settings.copy()  # save a copy to clean in place

    for tool in d.configured_tools:

        lprint("  Verifying safe settings for tool: " + str(tool), False)

        for setting in SAFE_RANGE.keys():
            low = SAFE_RANGE[setting][0]
            high = SAFE_RANGE[setting][1]
            other_values = SAFE_RANGE[setting][2]
            default_if_none = SAFE_RANGE[setting][3]
            try:
                v = dirty[tool][setting]
            except:
                lprint("Unconfigured tool in tool cleaner.  This shouldn't " +\
                       "happen.", error=True)
            if type(v) == str:
                if v.upper() in other_values:  # v has a safe value
                    continue
            if type(v) in [int, float]:
                if float(v) < float(low):
                    note = "  Minimum setting " + setting + " for " + \
                           tool + " enforced: " + str(low)
                    d.notices.append(note + "\n")
                    lprint(note)
                    dirty[tool][setting] = low
                elif float(v) > float(high):
                    note = "  Maximum setting " + setting + " for " + \
                           tool + " enforced: " + str(high)
                    d.notices.append(note + "\n")
                    dirty[tool][setting] = high
            elif v == None:
                dirty[tool][setting] = default_if_none
                note = str(tool) + "-" + str(setting) + \
                       ": used default value of " + \
                       str(default_if_none)
                d.notices.append(note + "\n")
    d.tool_settings = dirty  # save clean values
    d.apply_automatic_values()


def auto_calculate_insertion_length(d):
    """
    See detailed diagram at the bottom of this file for more information about this calculation.
    :param d: SetupData
    :return: float - insertion distance in mm.
    """
    tube_pos = float(d.gcode_vars['cooling_tube_retraction'])
    tube_length = float(d.gcode_vars['cooling_tube_length'])
    insertion_distance = tube_pos + (0.5 * tube_length) - 1.5
    d.auto_insertion_distance = insertion_distance + AUTO_INSERTION_DISTANCE_TWEAK
    lprint("Based on the data in this gcode file, your suggested insertion_length is %.1f" % d.auto_insertion_distance)
    return d.auto_insertion_distance


# SEARCH FUNCTIONS ***********************************************************
def get_settings(d):
    """
    extract settings from comments in filament start gcode and populate
    d.utool_settings (unverified settings from user)
    :param d: SetupData object
    :return: a string of gcode to be inserted in the output file

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
    chunks = re.finditer(SETTINGS_REGEX,
                         d.gcode_str, re.MULTILINE)
    # create dict that links the tool number to its settings profile
    if chunks is not None:
        for chunkNum, chunk in enumerate(chunks, start=0):
            if chunk is not None:
                toolname = str(chunk.group('previous_tool')).strip()
                config_string = chunk.group('parameters')
                lprint("ADDED data from chunk: " + str(chunkNum) + " previous_tool:" + toolname, False)
                config_strings[toolname] = config_string
                if toolname not in d.configured_tools:
                    d.configured_tools.append(toolname)
                    sortlist = sorted(d.configured_tools)
                    d.configured_tools = sortlist
                    lprint("Configured tools is now" + str(d.configured_tools), False)
    lprint("  finished scanning configuration strings.", False)
    lprint("  Configured extruders: " + str(d.configured_tools))
    lprint(pprint.pformat(config_strings), False)
    lprint("  Extracting settings dictionaries from config strings", False)
    for tool in d.configured_tools:
        tool_param_dict = {}
        tool_param_dict = extract_params(tool, config_strings[tool])
        d.utool_settings[tool] = merge_two_dicts(d.utool_settings[tool], tool_param_dict)

    # look up print temperatures to add to settings dict
    lprint("Scanning for main print temperature configuration...", False)
    print_temps_dict = get_temperature_config(d)
    lprint("Print temps are: " + str(print_temps_dict), False)

    for j in d.configured_tools:
        d.utool_settings[j]["print_temp"] = print_temps_dict[j]

    lprint("Settings before validation:\n" + str(pprint.pformat(d.utool_settings, indent=4) + "\n"), False)


def get_temperature_config(d):
    '''
    Scan gcode file for line that lists the temperature settings
    for every extruder.  The regex should return each temperature value
    as its own capture group.
    returns:  a dict of {"TO : [200,200,200,200,200], T1 ..}
    '''
    temperaturedict = {}
    temps = re.search(TEMPERATURE_REGEX, d.gcode_str)
    i = 0
    if temps is not None:
        for tool in TOOL_LIST:
            # print "tool "+str(tool)
            temperaturedict[tool] = int(temps.groups()[i])
            i += 1
        lprint("temperature config result:" + str(temperaturedict), False)
    else:
        lprint("No temperature configuration data in file.  Was it sliced with a  MMU profile?", error=True)

    return temperaturedict


def get_insertion_points(d):
    '''
     finds positions where insertions in the input file need to be
     made and indexes them.
     dip_index is dict of char locations in the file and the
     contents of those locations for further processing
     dip_positions is an ascending list of those locations used when
     building the output file. (faster than searching for
     existence of keys)
    '''


    matches = re.finditer(INSERTIONS_REGEX, d.gcode_str, re.MULTILINE)
    for matchNum, match in enumerate(matches, start=1):
        dip_pos = match.start("dip_pos")
        line_number = d.line_lookup[dip_pos]
        new_tool = match.group("new_tool")
        new_tool_pos = match.start("new_tool")
        previous_tool = d.tc_dict[new_tool_pos]["previous_tool"]
        temp_pause_pos = match.start("temp_pause")
        filament_temp = match.group("filament_temp")
        toolchange_temp = d.tool_settings[previous_tool]["toolchange_temp"]

        apply_temp_change = True
        if previous_tool not in d.configured_tools or \
                str(toolchange_temp).upper() in ["OFF", "0", "-1"]:
            apply_temp_change = False
        if apply_temp_change:
            if temp_pause_pos is not None:
                generate_wait_for_temp(d, temp_pause_pos)
        if filament_temp is None and apply_temp_change:
            temp_restore_pos = match.start("temp_restore")
            if temp_restore_pos is not None:
                generate_temp_restore(d, temp_restore_pos)
        try:

            bundle = {"previous_tool": previous_tool,
                      "new_tool": new_tool,
                      "new_tool_pos": new_tool_pos,
                      "line_number": line_number,
                      "output_gcode": generate_dip_gcode(d, previous_tool)
                      }
            d.dip_index[dip_pos] = bundle
            d.dip_positions.append(dip_pos)  # to speed up render process
            d.dip_lines.append(line_number)
        except Exception, e:
            lprint(str(e), error=True)


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


def get_temperature_change_positions(d):
    """
    In order to arrive at the set temperature a tiny bit sooner, a toolchange temperature
    is triggered just as the printer begins to move to the wipe tower.  This function
    locates these changes and generates a string of gcode for insertion which it stores
    in the SetupData object
    """
    # scan for temperature change patterns
    matches = re.finditer(TOOLCHANGE_TEMP_REGEX, d.gcode_str)
    for matchNum, match in enumerate(matches, start=1):
        if match is not None:
            changepos = int(match.start('temp_start'))
            line_number = d.line_lookup[changepos]
            tool_number = get_tool_from_filepos(d, changepos)
            toolchange_temp = d.tool_settings[tool_number]['toolchange_temp']
            if str(toolchange_temp).upper() not in ["OFF", "0", "-1"] and tool_number in d.configured_tools:
                tempbeep = ["", ""]
                if str(d.tool_settings[tool_number]["beep_on_temp"]).upper() in ["ON", "1"]:
                    tempbeep = TEMP_BEEP
                temper_change_gcode = ""
                temper_change_gcode += tempbeep[0]
                temper_change_gcode += "M104 S" + str(toolchange_temp) + \
                                       " ;***SKINNYDIP initiating " + str(
                    tool_number) + " toolchange temperature.  Target: " + str(toolchange_temp) + "***\n"
                temper_details = {'toolchange_number': 0,
                                  'tool_pos': changepos,
                                  'tool_number': tool_number,
                                  'toolchange_temp': toolchange_temp,
                                  'output_gcode': temper_change_gcode,
                                  'line_number': line_number,
                                  }
                d.temper_positions.append(changepos)  # to speed up render process
                d.temper_positions = sorted(d.temper_positions)  # required or some will be lost.
                d.temper_index[changepos] = temper_details
                d.temper_lines.append(line_number)
    temperlen = str(len(d.temper_index.keys()))
    lprint("  Temperature drop index has " + temperlen + " elements")
    lprint("\n" + pprint.pformat(d.temper_index) + "\n", False)


def get_extruder_settings(d):
    """
    Slic3r stores various useful variables in comments of its own in gcode.
    This function looks up a selection of useful variables and stores them.
    :param d: SetupData
    :return:
    """
    for var in VARS_FROM_SLIC3R_GCODE:
        pattern = regex_from_gcode_varname(var)
        result = re.search(pattern, d.gcode_str)
        if result is not None:
            value = str(result.group(var))
            d.gcode_vars[var] = value
            lprint("from gcode: " + str(var) + " = " + str(value))
        else:
            lprint("WARNING: " + str(var) + " not found in gcode file.")
    return


# MAIN PROGRAM****************************************************************
def main(target_file=None):
    """
    Primary loop of program.
    :param target_file: file name of input file.
    :return:
    """
    lprint("Skinnydip MMU2 String Eliminator v" + VERSION)
    d = SetupData(target_file)
    # try:
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
    get_insertion_points(d)
    lprint("Searching for initial temperature change gcode injection locations...")
    get_temperature_change_positions(d)
    lprint("Compiling final insertion list...")
    prepare_insertions(d)
    d.close_target_file()
    lprint("Preparing to build output file")
    d.open_target_file_lines()
    assemble_final_output(d)
    d.write_output_file_lines()
    d.write_log_file()
    lprint("Post processing complete.  Exiting...")
    exit(0)

    # These error handlers provide tidy error messages, but they are making bugs hard to track.
    # they are being disabled until this script comes out of beta
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
