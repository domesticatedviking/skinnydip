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
#  MODULES  ************************************************
from argparse import ArgumentParser
import fileinput
import re
import pprint
import os
import time
from shutil import copyfile

#  CONSTANTS ************************************************
VERSION = "0.3.0 beta"
TOOL_LIST = ["T0", "T1", "T2", "T3", "T4"] 
DEFAULT_SETTINGS={
        "material_type":       "PLA",
        "material_name":       "generic PLA",
        "toolchange_temp":     "-1",
        "print_temp":          "-1", 
        "insertion_speed":     "2000",
        "extraction_speed":    "4000",
        "insertion_pause":     "0",
        "insertion_distance":  "31",
        "removal_pause" :      "0",
        "debug_beep"    :      "False"
        }
NULL_SETTINGS_DICT={
        "material_type":       "N/A",
        "material_name":       "not configured",
        "toolchange_temp":     "-1",
        "print_temp":          "-1",
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
        "insertion_distance":  [0,60],
        "removal_pause" :      [0,20000],
        "print_temp"    :      [150,295],
        "toolchange_temp":     [150,295] 
        } 
TOOLCHANGE_TEMP_SAFE_RANGE = [150,295]
CONFIGSTRING_REGEX = r"(SKINNYDIP CONFIGURATION START.?)(?P<configstring>.*)"
SET_ITEMS=["material_type", "material_name", "insertion_speed", 
           "extraction_speed", "insertion_pause", "insertion_distance", 
           "removal_pause", "toolchange_temp"]
TOOLCHANGE_TEMP_REGEX=r"; CP TOOLCHANGE START\n; toolchange #(?P<toolchange_number>\d*\n);.*\n;.*\nM220 B\nM220 S(?P<speed_factor>\d*)\n(?P<temp_change_pos>; CP TOOLCHANGE UNLOAD)"
ASSOCIATE_TOOL_WITH_SETTINGS_REGEX =r"(?<=(?P<previous_tool>T[01234]\n))(?P<otherstuff>(\w|\d|\n|[().,\-:;@#$%^&*\[\]\"'+–/\/®°⁰!?{}|`~]|.?)+?(?=(;.?SKINNYDIP CONFIGURATION END)))"
COOLING_MOVE_REGEX = r"G1 E.*\n(?:M73.*\n)?G1.*\n(?:M73.*\n)?G4 S0\n(?:M73.*\n)?(?P<tool>(T[0-4])|(M220 R))"
TOOLCHANGE_REGEX = r"(?P<tool>\nT[0-4]\n)"
FINAL_TOOLCHANGE_REGEX = r"G1 E.*\nG1.*\nG4 S0\n(?P<final>M2)20 R" #NEEDS TO BE FIXED -M73
TEMPERATURE_REGEX= regex = r"; temperature = (...),(...),(...),(...),(...)"

#  GLOBAL ****************************************************
logtext = ""


class CustomError(Exception):
    pass

def raw_string(s):
    if isinstance(s, str):
        s = s.encode('string-escape')
    elif isinstance(s, unicode):
        s = s.encode('unicode-escape')
    return s

def regex_from_paramstr(paramstr):
    raw_ps=raw_string(paramstr)
    pattern=r";.*"+raw_ps+r" (?P<"+raw_ps+r">.*)\n"
    return pattern
       



def get_dip_gcode(toolnumber, settingsdict):
    insertion_distance = settingsdict[toolnumber]["insertion_distance"]
    insertion_speed = settingsdict[toolnumber]["insertion_speed"]
    extraction_speed = settingsdict[toolnumber]["extraction_speed"]
    material_name = settingsdict[toolnumber]["material_name"]
    material_type = settingsdict[toolnumber]["material_type"]
    toolchange_temp = settingsdict[toolnumber]["toolchange_temp"]
    insertion_pause = settingsdict[toolnumber]["insertion_pause"]
    removal_pause = settingsdict[toolnumber]["removal_pause"]

    dip_gcode = ""
    dip_gcode += ";*****SKINNYDIP THREAD REDUCTION*****************\n"
    dip_gcode += "; Tool(" + toolnumber + "), " + material_type+"/"\
                    + material_name+"\n"
    if float(insertion_distance) > 0 and float(insertion_speed) > 0:
        dip_gcode += "G1 E" + str(insertion_distance) + " F"+\
                      str(insertion_speed) +\
                     "    ;move stringy tip into melt zone\n"
    if int(insertion_pause)>0:
        dip_gcode += "G4 P" + str(insertion_pause)+\
                     "        ; pause in melt zone\n"

    if float(insertion_distance) > 0 and float(extraction_speed) > 0:
        dip_gcode += "G1 E-" + str(insertion_distance) + " F" +\
                      extraction_speed+\
                      "   ;extract clean tip from melt zone\n"
    if int(removal_pause)>0:
        dip_gcode += "G4 P" + str(removal_pause)+\
        "        ; pause in cool zone\n"
    dip_gcode += ";************************************************\n"
    return dip_gcode



def extract_params(tool, paramstr):
    out_dict={}
    for param in SET_ITEMS:
        regex=regex_from_paramstr(param)

        try:
            matches=re.search(regex, paramstr, re.MULTILINE)
            if matches is not None:
                thisitem=str(matches.group(param))
                #lprint (str(tool)+":  "+str(param)+" = " + str(matches.group(param)), False)
                out_dict[param]=thisitem

        except Exception, e:
            print str(e)
            lprint ("no matches for "+tool+": regex"+regex)
            out_dict[param] = -1
            pass
    #print "returning out_dict for "+tool+" "+ pprint.pformat(out_dict)
    return out_dict





def get_settings(gcode_str):
    tool_settings = {}  #dict to store configuration for each tool
    config_strings= {}
    #Initialize tool settings to null settings
    for i in TOOL_LIST:
        tool_settings[i]=NULL_SETTINGS_DICT


    #gcode_str = f.read()

    #search for text chunk containing tool numbers and associated 
    #configuration strings.

    chunks = re.finditer(ASSOCIATE_TOOL_WITH_SETTINGS_REGEX, 
                          gcode_str, re.MULTILINE) 
    for chunkNum, chunk in enumerate(chunks, start=1):
        #grab tool number from beginning of chunk
        toolname=str(chunk.group('previous_tool')).strip()

        #isolate settings substring from text chunk
        configmatch=re.search(CONFIGSTRING_REGEX, str(chunk.group('otherstuff')), re.MULTILINE | re.DOTALL)
        config_strings[toolname]= str(configmatch.group('configstring'))

    lprint ("  finished scanning configuration strings.",False)
    lprint (pprint.pformat(config_strings, indent=4), False)
      
    lprint ("  Extracting settings dictionaries from config strings", False)
    for tool in TOOL_LIST:
        tool_param_dict={}
        try:
            tool_param_dict=extract_params(tool,config_strings[tool])
        except:
            tool_param_dict=NULL_SETTINGS_DICT
        tool_settings[tool] = tool_param_dict
       
    #look up print temperatures to add to settings dict
    print_temps_dict=get_temperature_config(gcode_str)
    #values fine until here    
    
    for j in TOOL_LIST:
        tool_settings[j]["print_temp"]=print_temps_dict[j]
    return tool_settings
     

def index_dip_insertion_points(text):
    '''
     finds positions where insertions in the input file need to be
     made and indexes them
     dip_index is dict of pointers to locations in the file and the
     contents of those locations for further processing
     dip_positions is an ascending list of those locations used when
     building the output file. (faster than searching for 
     existence of keys)
    '''

    dip_index = {}
    dip_positions = []
    gcode_str = text
    #look for regex associated with place where skinnydip is needed
    matches = re.finditer(COOLING_MOVE_REGEX, gcode_str, re.MULTILINE)
    for matchNum, match in enumerate(matches, start=1):
        matchpos=int(match.start())
        matchcontents=str(match.group()).strip()
        dip_index[matchpos] = matchcontents
        dip_positions.append(matchpos) #to speed up render process
    return dip_index, dip_positions 

def get_temperature_config(gcode_str):
    '''
    Scan gcode file for line that lists the temperature settings
    for every extruder.  The regex should return each temperature value
    as its own capture group.
    '''
    temperaturedict={}
    temps=re.search(TEMPERATURE_REGEX, gcode_str)
    i=0
    for tool in TOOL_LIST:
        #print "tool "+str(tool)
        temperaturedict[tool] = str(temps.groups()[i])
        i+=1
    lprint("temperature config result:" + str(temperaturedict), False)
    return temperaturedict



def index_temperature_change_positions(gcode_str, tool_sequence, settingsdict):
    '''
    TOOLCHANGE_TEMP_REGEX=r"; CP TOOLCHANGE START\n; toolchange #(?P<toolchange_number>\d*\n);.*\n;.*\nM220 B\nM220 S(?P<speed_factor>\d*)\n(?P<temp_change_pos>; CP TOOLCHANGE UNLOAD)"
    groups = toolchange_number (for looking up temperature that was set)
    speed_factor (location of an acceleration value that could be altered)
    temp_change_pos(place to inject the new temperature)

    '''
    SEQ_SHIFT=0
    temper_index = {}
    temper_details={}
    temper_positions = []
    #scan for temperature change patterns
    matches = re.finditer(TOOLCHANGE_TEMP_REGEX, gcode_str, re.MULTILINE)
    
    for matchNum, match in enumerate(matches, start=1):
        changepos=int(match.start('temp_change_pos'))
        temper_positions.append(changepos) #to speed up render process

      
        toolchange_number=int(match.group('toolchange_number'))
        tool=tool_sequence[toolchange_number + SEQ_SHIFT]
        toolchange_temp=settingsdict[tool]['toolchange_temp']
        temper_change_gcode="M104 S"+str(toolchange_temp)+" ;***SKINNYDIP Toolchange Temperature Adjustment***\n" 

        temper_details={'toolchange_number': toolchange_number,
                        'tool' : tool,
                        'toolchange_temp' : toolchange_temp,
                        'temper_change_gcode' : temper_change_gcode,
                        'temp_change_marker_text' : match.group('temp_change_pos')}


        temper_index[changepos] = temper_details


    return temper_index, temper_positions



def index_toolchanges(gcode_str):
    '''
    Indexes locations of tool changes in the gcode, and creates a dictionary
    that allows us to know what tool is currently active (the tool activated
    by the previous toolchange).   

    '''
    tc_dict = {}
    tc_list = []
    matches = re.finditer(TOOLCHANGE_REGEX, gcode_str, re.MULTILINE)

    prev_tool = None

    for matchNum, match in enumerate(matches, start=0):
        matchpos = int(match.start('tool')) + 1  #add 1 because of initial newline
        matchcontents = str(match.group('tool')).strip() 
        tc_dict[matchpos]={'new_tool' : matchcontents,
                'current_tool' : prev_tool}
        prev_tool = matchcontents
        tc_list.append(matchcontents)

    
    #final tool removal doesn't match the regular pattern.
    #There is also no toolchange lookup possible because there
    #is no actual toolchange here.  So we have to fake one.

    final=re.search(FINAL_TOOLCHANGE_REGEX, gcode_str) 
    #look up the capture group at index 1, pad so the lookup will
    #find a value to use
    finalpos=int(final.start(1))+4
    #sanity check, line should contain M220 R
    if str(final.groups("final")[0]) != "M2": #group
        errortext="Error with final toolchange.  Unexpected value"+\
			str(final.groups("final"))
        lprint ("ERROR:  "+errortext)
        raise CustomError(errortext)
                
    else:
        tc_dict[finalpos]={"new_tool" : "end",
                           "current_tool" : prev_tool}
    tool_sequence=tc_list
    return tc_dict, tool_sequence


def build_output(text, settingsdict, tc_list, dip_index, dip_positions, temper_index, temper_positions):
    ts= time.gmtime()
    out = "; SKINNYDIP THREAD REDUCTION v" + VERSION + " postprocessing "+\
          "completed on " + (time.strftime("%x %X", ts)) +"\n"
    len_chars = len(text)
    current_insertion = 0
    i = 0
    while (i < len_chars):
        
        

        dipmatch=False
        tempermatch=False
        try:
            #check if current pos is indexed as an insertion point.
            dipmatch = (i == dip_positions[current_insertion])
            tempermatch= (i == temper_positions[current_insertion])
        except Exception, e:
            pass


        if dipmatch:
            #INJECT SKINNYDIP CODE
            addtext=""
            #retrieve the previously saved text (goes after the insertion)
            oldtext=dip_index[i]   

            #get location of the toolchange characters at the end of the
            #previously saved text
            toolchange_substr_pos = i + (len(oldtext))-2
            #use the position of the toolchange text to look up the tool
            #that was active when that toolchange was called
            current_tool = tc_list[toolchange_substr_pos]["current_tool"]
            if current_tool is not None:
                inserted_text = get_dip_gcode(current_tool, settingsdict)
                addtext = inserted_text
                out += addtext +str(text[i])
                i += 1
                current_insertion += 1

        elif tempermatch:
            #INJECT TEMPDROP CODE
            addtext=""
            #retrieve the previously saved text (goes after the insertion)
            oldtext=temper_index[i]['temp_change_marker_text']
            temper_change_gcode = temper_index[i]['temper_change_gcode']
            inserted_text=temper_change_gcode
            out += inserted_text +str(text[i])
            i += 1
            current_insertion += 1


        else:
            out += str(text[i])
            i += 1
    return out
    
def cleanSettings(ds):
    for tool in TOOL_LIST:
        lprint ("  Verifying safe settings for tool: "+str(tool), False)
        for setting in SAFE_RANGE.keys():
            try:
                v=ds[tool][setting]
            except:
                v=None
            lprint ("    "+str(tool)+": "+setting+" = "+str(v),False)
            low=SAFE_RANGE[setting][0]
            high=SAFE_RANGE[setting][1]
            if v is not None:
                if float(v) < float(low):
                    lprint("  Minimum setting "+setting+" for "+\
                      tool+" enforced: "+str(low))
                    ds[tool][setting] = str(low)

                if float(v) > float(high):
                    lprint("  Maximum setting "+setting+" for "+\
                      tool+" enforced: "+str(high))
                    ds[tool][setting] = str(high)

            if ds[tool]["toolchange_temp"]>0:
                if float(ds[tool]['toolchange_temp']) < float(TOOLCHANGE_TEMP_SAFE_RANGE[0]):
                    lprint("  Minimum setting "+setting+" for "+\
                          tool+" enforced: "+str(TOOLCHANGE_TEMP_SAFE_RANGE[0]))
                    ds[tool]['toolchange_temp'] = TOOLCHANGE_TEMP_SAFE_RANGE[0]

                if float(ds[tool]['toolchange_temp']) > TOOLCHANGE_TEMP_SAFE_RANGE[1]:
                    lprint("  Maximum setting "+setting+" for "+\
                          tool+" enforced: "+str(TOOLCHANGE_TEMP_SAFE_RANGE[1]))
                    ds[tool]['toolchange_temp'] = SAFE_RANGE[setting][1]
            else:
                lprint ("Value was missing for : "+str(tool)+"-"+str(setting))
   

    return ds


def lprint(message, display=True):
    global logtext
    logtext += (message)+"\n"
    if display:
        print message



def main():

    lprint ("\nSkinnydip MMU2 String Eliminator v"+VERSION)
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
        lprint('File received for processing was {}'.format(args.myFile))
    else:
        lprint('No file received as an argument')
        outputfilename = "noname_skinnydip.gcode"
    try:
        f = open(myFile)
        text=str(f.read())
        if text[:11] == "; SKINNYDIP":
            raise CustomError("File was previously processed by this "\
                              "script.  Terminating.")
        lprint ("Scanning gcode for configuration parameters...")
        dirtysettingsdict = get_settings(text)
        lprint ("Done.")
        lprint ("Settings before validation:\n"+str(pprint.pformat(dirtysettingsdict, indent=4)+"\n"), False)

        lprint ("Validating User Settings...")
        settingsdict=cleanSettings(dirtysettingsdict)
        lprint ("Done.")
        lprint ("Indexing toolchanges...")
        tc_list, tool_sequence = index_toolchanges(text)
        lprint ("Done.")
        lprint ("Getting temperature config...")
        tc=get_temperature_config(text)
        lprint ("Done.")
        lprint ("Searching for gcode injection locations...")
        dip_index , dip_positions  = index_dip_insertion_points(text)
        lprint ("Done.")
        lprint ("Searching for temperature drop injection locations...")
        temper_index, temper_positions=index_temperature_change_positions(text, tool_sequence, settingsdict)
        lprint (pprint.pformat(temper_index), False)
        lprint ("Done.")

        lprint ("Building post processed file...")
        out = build_output(text, settingsdict, tc_list, dip_index, dip_positions, temper_index, temper_positions)
        lprint ("Done.")
        f.close()
        lprint ("temporarily storing post processed output as "+outputfilename)
        outfile = open(outputfilename,'w')
        outfile.write(out)
        outfile.close()
        if keep_original:
            lprint ("renaming original file as "+bakfilename)
            os.rename(inputfull, bakfilename)
        else:
            lprint ("deleting original file: "+inputfull)
            os.remove(inputfull)
        lprint ("moving post processed output to "+inputfull)
        os.rename(outputfilename, inputfull)
        lprint ("post processing complete.")
        logfile=open("skinnydip.log","w")
        logfile.write(logtext)
        logfile.close()

    except Exception, e:
        logfile=open("skinnydip.log","w")
        errorstring= "ERROR: " + str(e)
        lprint (errorstring)
        logfile.write(logtext)
        logfile.close()
        exit(-1)
        raise

main()
