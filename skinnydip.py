#!/usr/bin/python
# coding=utf8
'''
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
'''

from argparse import ArgumentParser
import fileinput
import re
import pprint
import os
import time
from shutil import copyfile

VERSION = "0.1.3 beta"
TOOL_LIST = ["T0", "T1", "T2", "T3", "T4"] 
DEFAULT_SETTINGS={
        "material_type":       "PLA",
        "material_name":       "generic PLA",
        "insertion_speed":     "2000",
        "extraction_speed":    "4000",
        "insertion_pause":     "0",
        "insertion_distance":  "31",
        "removal_pause" :      "0"
        }
NULL_SETTINGS_DICT={
        "material_type":       "N/A",
        "material_name":       "Not configured",
        "insertion_speed":     "0",
        "extraction_speed":    "0",
        "insertion_pause":     "0",
        "insertion_distance":  "0",
        "removal_pause" :      "0"
        }
SAFE_RANGE={
        "insertion_speed":     [300,10000],
        "extraction_speed":    [300,10000],
        "insertion_pause":     [0,20000],
        "insertion_distance":  [0,40],
        "removal_pause" :      [0,20000]
        } 
CONFIGURATION_REGEX = r"M900 K.*\n; SKINNYDIP CONFIGURATION START\n(; material_type .*\n; material_name "\
                       ".*\n; insertion_speed .*\n; extraction_speed.*\n; insertion_pause.*\n; insertion_distance.*\n; removal_pause.+)"
SET_ITEMS=["material_type", "material_name", "insertion_speed", 
           "extraction_speed", "insertion_pause", "insertion_distance", 
           "removal_pause"]
ASSOCIATE_TOOL_WITH_SETTINGS_REGEX = r"(?<=(T[01234]\n))(\w|\d|\n|[().,\-:;@#$%^&*\[\]\"'+–/\/®°⁰!?{}|`~]| )+?(?=(SKINNYDIP CONFIGURATION END))"
#COOLING_MOVE_REGEX = r"G1 E.*\nG1.*\nG4 S0\nT[0-4]" 
COOLING_MOVE_REGEX = r"G1 E.*\nG1.*\nG4 S0\n((T[0-4])|(M220 R))" 
TOOLCHANGE_REGEX = r"\nT[0-4]\n"
FINAL_TOOLCHANGE_REGEX = r"G1 E.*\nG1.*\nG4 S0\n(M2)20 R"



class CustomError(Exception):
    pass


def get_dip_gcode(toolnumber, settingsdict):
    insertion_distance = settingsdict[toolnumber]["insertion_distance"]
    insertion_speed = settingsdict[toolnumber]["insertion_speed"]
    extraction_speed = settingsdict[toolnumber]["extraction_speed"]
    material_name = settingsdict[toolnumber]["material_name"]
    material_type = settingsdict[toolnumber]["material_type"]
    insertion_pause = settingsdict[toolnumber]["insertion_pause"]
    removal_pause = settingsdict[toolnumber]["removal_pause"]

    dip_gcode = ""
    dip_gcode += ";*****SKINNYDIP THREAD REDUCTION*****************\n"
    dip_gcode += "; Tool(" + toolnumber + "), " + material_type+"/"\
                    + material_name+"\n"
    if float(insertion_distance) > 0 and float(insertion_speed) > 0:
        dip_gcode += "G1 E" + insertion_distance + " F" + insertion_speed +\
                     "    ;move stringy tip into melt zone\n"
    if int(insertion_pause)>0:
        dip_gcode += "G4 P" + insertion_pause+"        ; pause in melt zone\n"

    if float(insertion_distance) > 0 and float(extraction_speed) > 0:
        dip_gcode += "G1 E-" + insertion_distance + " F" + extraction_speed+\
                      "   ;extract clean tip from melt zone\n"
    if int(removal_pause)>0:
        dip_gcode += "G4 P" + removal_pause+"        ; pause in cool zone\n"
    dip_gcode += ";************************************************\n"
    return dip_gcode


def get_settings(gcode_str):
    tool_settings = {}  #dict to store configuration for each tool
    #gcode_str = f.read()
    #print str(type(test_str))

    #search for text chunk containing tool numbers and associated 
    #configuration strings.
    matches = re.finditer(ASSOCIATE_TOOL_WITH_SETTINGS_REGEX, 
                          gcode_str, re.MULTILINE) 
    #matches = re.finditer(configuration_regex, test_str, re.MULTILINE)

    #iterate over text chunks so that we can filter only the pertinent
    #configuration strings.
    for matchNum, match in enumerate(matches, start=1):
        #isolate settings substring from text chunk
        secondmatches = re.finditer(CONFIGURATION_REGEX, match.group(), 
                                    re.MULTILINE)
        for secondmatchNum, secondmatch in enumerate(secondmatches, start=1): 
            store_string= str(secondmatch.group(1)).strip() #clean up substring
            toolname=(match.group(1)).strip()
            tool_settings[toolname] = store_string #save substring for each tool
    #Build itemized dictionary of settings for each material
    settingsdict = {}
    #Initialize tool settings to null settings
    for i in TOOL_LIST:
        settingsdict[i]=NULL_SETTINGS_DICT
    cleanlist = []
    for item, value in enumerate(tool_settings):
        settingsdict[value] = {}  #initialize contents of each value as dict
        settinglist = tool_settings[value].splitlines()
        for i in settinglist:
            cleanlist.append(str(i.replace("; ", "")).strip()) #clean strings
        #populate settings dictionary
        for cleanindex, cleanvalue in enumerate(cleanlist):
            param=cleanlist[cleanindex].split(None,1)
            settingsdict[value][param[0]] = param[1]
    return settingsdict
     

def index_insertion_points(text):
    '''
     finds positions where insertions in the input file need to be
     made and indexes them
     ins_index is dict of pointers to locations in the file and the
     contents of those locations for further processing
     ins_positions is an ascending list of those locations used when
     building the output file. (faster than searching for 
     existence of keys)
    '''

    ins_index = {}
    ins_positions = []
    gcode_str = text
    #look for regex associated with place where skinnydip is needed
    matches = re.finditer(COOLING_MOVE_REGEX, gcode_str, re.MULTILINE)
    for matchNum, match in enumerate(matches, start=1):
        matchpos=int(match.start())
        matchcontents=str(match.group()).strip()
        ins_index[matchpos] = matchcontents
        ins_positions.append(matchpos) #to speed up render process
    return ins_index, ins_positions 


def index_toolchanges(gcode_str):
    tc_dict = {}
    tc_list = []
    matches = re.finditer(TOOLCHANGE_REGEX, gcode_str, re.MULTILINE)
    prev_tool = None
    
    for matchNum, match in enumerate(matches, start=1):
        matchpos = int(match.start()) + 1  #add 1 because of initial newline
        matchcontents = str(match.group()).strip()
        tc_dict[matchpos]={'new_tool' : matchcontents,
                'current_tool' : prev_tool}
        prev_tool = matchcontents
        tc_list.append(matchcontents)
        #pprint.pprint(tc_dict)
        #pprint.pprint(tc_list)
    
    #final tool removal doesn't match the regular pattern.
    #There is also no toolchange lookup possible because there
    #is no actual toolchange here.  So we have to fake one.

    final=re.search(FINAL_TOOLCHANGE_REGEX, gcode_str) 
    #look up the capture group at index 1, pad so the lookup will
    #find a value to use
    finalpos=int(final.start(1))+4

    #sanity check, line should contain M220 R
    if str(final.group(1)) != "M2":
        raise CustomError("Error with final toolchange.  Unexpected value"+
                          str(final.group(1)))
    else:
        tc_dict[finalpos]={"new_tool" : "end",
                           "current_tool" : prev_tool}

        
        




    return tc_dict


def build_output(text, settingsdict, tc_list, ins_index, ins_positions):
    ts= time.gmtime()
    out = "; SKINNYDIP THREAD REDUCTION v" + VERSION + " postprocessing "+\
          "completed on " + (time.strftime("%x %X", ts)) +"\n"
    len_chars = len(text)
    #print "Number of characters in this file:" +str( len_chars)
    current_insertion = 0
    i = 0
    
    while (i < len_chars):
        match=False
        try:
            #check if current pos is indexed as an insertion point.
            match = (i == ins_positions[current_insertion])
        except Exception, e:
            pass

        if match:
            addtext=""
            #retrieve the previously saved text (goes after the insertion)
            oldtext=ins_index[i]   

            #get location of the toolchange characters at the end of the
            #previously saved text
            toolchange_substr_pos = i + (len(oldtext))-2

            #use the position of the toolchange text to look up the tool
            #that was active when that toolchange was called
            current_tool = tc_list[toolchange_substr_pos]["current_tool"]
            if current_tool is not None:
                inserted_text = get_dip_gcode(current_tool, settingsdict)
                addtext = inserted_text
                out += addtext +text[i]
                i += 1
                current_insertion += 1
        else:
            out += text[i]
            i += 1
    return out
    
def cleanSettings(ds):
    for tool in TOOL_LIST:
        for setting in SAFE_RANGE:
            if float(ds[tool][setting]) < SAFE_RANGE[setting][0]:
                print "  Minimum setting "+setting+" for "+\
                      tool+" enforced: "+str(SAFE_RANGE[setting][0])
                ds[tool][setting] = SAFE_RANGE[setting][0]

            if float(ds[tool][setting]) > SAFE_RANGE[setting][1]:
                print "  Maximum setting "+setting+" for "+\
                      tool+" enforced: "+str(SAFE_RANGE[setting][1])
                ds[tool][setting] = SAFE_RANGE[setting][1]
    return ds



def main():
    print "\n\nSkinnydip MMU2 String Eliminator v"+VERSION
    parser = ArgumentParser()
    parser.add_argument(dest="myFile", help="open a file")
    parser.add_argument("--k", "--keep", action='store_true', 
                        help="keep copy of original file")
    args = parser.parse_args()
    keep_original=args.k
    myFile = args.myFile
    #plan filenames for output files
    if myFile is not None:
        inputfilename = os.path.splitext(args.myFile)[0]
        inputextension = os.path.splitext(args.myFile)[1]
        inputfull = inputfilename+inputextension
        outputfilename = inputfilename + "_skinnydip" + inputextension
        bakfilename = inputfilename+"_original"+inputextension
        print('File received for processing was {}'.format(args.myFile))
    else:
        print('No file received as an argument')
        outputfilename = "noname_skinnydip.gcode"
    try:
        f = open(myFile)
        text=str(f.read())
        if text[:11] == "; SKINNYDIP":
            raise CustomError("File was previously processed by this "\
                              "script.  Terminating.")
        print "Scanning gcode for configuration parameters...",
        dirtysettingsdict = get_settings(text)                     
        print "Done"
        print "Validating User Settings..."
        settingsdict=cleanSettings(dirtysettingsdict)
        print "Done"
        print "Indexing toolchanges...",
        tc_list = index_toolchanges(text)
        print "Done"
        print "Searching for gcode injection locations...",
        ins_index , ins_positions  = index_insertion_points(text)
        print "\n\nMake sure final toolchange is in here!"
        pprint.pprint(ins_index)
        print "Done"
        print "Building post processed file..."
        out = build_output(text, settingsdict, tc_list, ins_index, ins_positions)
        print "Done"
        f.close()
        print "temporarily storing post processed output as "+outputfilename
        outfile = open(outputfilename,'w')
        outfile.write(out)
        outfile.close()
        if keep_original:
            print "renaming original file as "+bakfilename
            os.rename(inputfull, bakfilename)
        else:
            print "deleting original file: "+inputfull
            os.remove(inputfull)
        print "moving post processed output to "+inputfull
        os.rename(outputfilename, inputfull)
        print "post processing complete."
    except Exception, e:
        print "ERROR: " + str(e)
        f.close()
    finally:
        logfile=open("skinnydip.log","w")
        logfile.write("Successfully ran. output file was: "+outputfilename)
        logfile.close()

main()
