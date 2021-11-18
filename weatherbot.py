#!/usr/bin/env python3
# weatherbot.py
#
# Python script to grab temperature data from the US National Weather Service and display on scrollphathd. This script shows the current temperature along with an indicator of
#  the temperature trend (same, going up, going down), averaged over a given period of time. It also shows a small line at the bottom which indicates current 
#  wind speed and gusts. Current speed is shown using a brighter color and gusts are show using a dimmer color.
#
# Development environment: Python v3 on a Raspberry Pi Zero-W running Raspbian, default scrollphathd libraries, and pyowm python library.
#
# Original version by Mark Ehr, 1/12/18. Released to the public domain with no warranties expressed or implied. Or something along those lines. Feel free to use
#	this code any way that you'd like. If you want to give me credit, that's great. 
# OWM version by Scott Hoge, 11/23/2020. Ditto the above. :-)
# Revised 11/18/2021 to use the US NWS API
#
# Installation notes:
#	# pip install python-dotenv
#    * Do one of the following:
#    	# sudo apt-get install python3-scrollphathd 
#       # sudo pip3 install scrollphat
# 	# curl https://get.pimoroni.com/scrollphathd | bash
#    * The scrollphat requires I2C enabled. Make sure that is turned on in raspi-config if the install above doesn't enable it.
#
# Note: if you want this to auto-run upon boot, add this line to the bottom of /etc/rc.local just above the "exit 0" line:
#	sudo python3 {path}/weatherbot.py &
#
# Also note that if you receive an odd "Remote I/O" error, that's the scrollphathd's odd way of saying that it can't 
#	communicate with the display. Check the hardware connection to make sure all of the pins are seated. In my case, it
#	happened randomly until I re-soldered the header connections on the RPi as well as the hat.
#

import scrollphathd #default scrollphathd library
from scrollphathd.fonts import font3x5
import time	#returns time values
import os
import sys
import getopt
import logging
import urllib3
import socket
import requests
import json
from StreamToLogger import StreamToLogger

# get WEATHER_STATION from .env file
from dotenv import load_dotenv
load_dotenv()

#log to /var/log/weatherbot.log
#logging.basicConfig(filename='weatherbot.log', level=logging.INFO)

#log = logging.getLogger('weatherbot')
#sys.stdout = StreamToLogger(log, logging.INFO)
#sys.stderr = StreamToLogger(log, logging.ERROR)

USAGE = f"Usage: python3 {sys.argv[0]} [-h|--help] | [-v|--version] | [-d|--debug]"
VERSION = f"{sys.argv[0]} version 1.0.0"

# Debug flag  - set to 1 if you want to print(informative console messages)
DEBUG = 0

def parse():
	global DEBUG

	options, arguments = getopt.getopt(
		sys.argv[1:],			# Arguments
		'vhd',				# Short option definitions
		["version", "help", "debug"])	# Long option definitions
	for o, a in options:
		if o in ("-v", "--version"):
			print(VERSION)
			sys.exit()
		if o in ("-h", "--help"):
			print(USAGE)
			sys.exit()
		if o in ("-d", "--debug"):
			DEBUG = 1
	if len(arguments) > 1:
		raise SystemExit(USAGE)
	try:
		operands = [int(arg) for arg in arguments]
	except ValueError:
		raise SystemExit(USAGE)
	return operands

operands = parse()

# Uncomment the below if your display is upside down
#   (e.g. if you're using it in a Pimoroni Scroll Bot)
scrollphathd.rotate(degrees=180)

WEATHER_STATION = os.environ.get("WEATHER_STATION","KHEF")

# Weather polling interval (seconds). Free Wunderground API accounts allow 500 calls/day, so min interval of 172 (every ~2.88 min), assuming you're only making 1 call at a time.
POLL_INTERVAL = 180

# Interval after which the average temp is reset. Used to make sure that the temp trending indicator stays accurate. Default is 60 min.
AVG_TEMP_RESET_INTERVAL = 60

# Flags used to specify whether to display actual or "feels like" temperature.
# Change CURRENT_TEMP_DISPLAY to 1 for actual temp and anything other than 1 for feels like temperature
CURRENT_TEMP_DISPLAY = 1 #feels like

# Display settings
BRIGHT = 0.2
DIM = 0.1
GUST_BRIGHTNESS = 0.2 #show gusts as a bright dot
WIND_BRIGHTNESS = 0.1 #show current speed as a slightly dimmer line

# "Knight Rider" pulse delay. See comments below for description of what this is.
#	Note that this loop uses the lion's share of CPU, so if your goal is to minimize CPU usage, increase the delay.
#	Of course, increasing the delay results in a slightly less cool KR pulse. In practice, a value of 0.05 results in ~16% Python CPU utilization on
#	a Raspberry Pi Zero-W. Increasing this to 0.1 drops CPU to ~10%, of course YMMV. 
KR_PULSE_DELAY = 0.05

# Temperature scale (C or F). MUST USE UPPERCASE.
TEMP_SCALE = "F"

# Max wind speed. Used to calculate the wind speed bar graph (17 "x" pixels / max wind speed = ratio to multiply current wind speed by in order to
#	determine much much of a line to draw)
if TEMP_SCALE == "F": #set max wind speed according to scale
	MAX_WIND_SPEED = 75.0 #MPH; default 75.0
	UNITS="fahrenheit"
else:
	MAX_WIND_SPEED = 100.0 #KPH; default 100.0
	UNITS="celsius"

#Initialize global variables before use
current_temp = 0.0
average_temp = 0.0
wind_chill = 0.0
average_temp_counter = 0
average_temp_cumulative = 0.0
total_poll_time = 0 #used to reset the average temp after a defined amount of time has passed
wind_speed = 0.0
wind_gusts = 0
actual_str = " "
feels_like_str = " "
feels_like = 0

#
# get_weather_data() - Retrieves and parses the weather data we want to display from Wunderground. Returns a formatted temperature string
#	using the specified scale. To request a free API key, go here: https://www.wunderground.com/weather/api/d/pricing.html
#

def get_weather_data():
	# Make sure that the module updates the global variables instead of creating local copies
	global current_temp
	global average_temp_cumulative

	global average_temp_counter
	global average_temp
	global wind_speed
	global wind_gusts
	global current_str
	global actual_str
	global feels_like_str
	global feels_like

	http = urllib3.PoolManager()

	#Get current conditions. 
	trycount = 0
	url = "https://api.weather.gov/stations/" + WEATHER_STATION + "/observations/latest"
	try:
		conditions = http.request("GET",url,headers={"User-Agent":"(weatherbot,scott.hoge@gmail.com)"})
	except (urllib3.exceptions.ReadTimeoutError, socket.timeout, requests.exceptions.ReadTimeout):
		print("TIMEOUT ERROR: ", sys.exc_info()[0])
		trycount += 1
		time.sleep(10)
	except e:
		raise(e)

	if trycount > 0:
		print(f'Took {trycount} retries to get weather.')

	parsed_cond = json.loads(conditions.data.decode('utf-8'))
	conditions.close()

	#build current temperature string

	# Check to see if average temp counters need to be reset
	if (average_temp_counter * POLL_INTERVAL / 60) > AVG_TEMP_RESET_INTERVAL:
		average_temp_cumulative = 0.0
		average_temp_counter = 0
		if DEBUG:
			print("Resetting average temp counters")

	# parse out the current temperature and wind speeds from the json catalog based on which temperature scale is being used
	temperature = str(1.8*(parsed_cond['properties']['temperature']['value'])+32)
	current_temp = (1.8*(parsed_cond['properties']['temperature']['value'])+32)
	#feels_like = float(temp['feels_like'])

	#wind = obs.wind(unit='miles_hour')
	wind_speed = float(parsed_cond['properties']['windSpeed']['value'])
	wind_gusts = float(parsed_cond['properties']['windGust']['value'])
	
	# Calculate average temperature, which is used to determine temperature trending (same, up, down)
	average_temp_cumulative = average_temp_cumulative + current_temp
	average_temp_counter = average_temp_counter + 1
	average_temp = average_temp_cumulative / average_temp_counter
	fl_int = int(feels_like) #convert to integer from float. For some reason you can't cast the above directly as an int, so need to take an extra step. I'm sure there is a more elegant way to doing this, but it works. :-)
	fl_str = str(fl_int)
	as_int = int(current_temp)
	actual_str = str(as_int)
	if DEBUG:
		print("get_weather_data()")
		print("Current temp", current_temp, TEMP_SCALE)
		print("Average temp" , average_temp , TEMP_SCALE)
		print("Feels like", feels_like, TEMP_SCALE)
		print("Wind speed: ", wind_speed)
		print("Wind gusts: ", wind_gusts)
		print("Feels like string: [", fl_str, "]")
		print("Temperature string: [", actual_str, "]")

	#
	# If you want to play around with displaying other measurements, here are a few you can use. You can view the entire menu by pasting the wunderground
	#	URL above into a web browser, which will return the raw json output. 
	#

	#humidity = temp['humidity']
	#precip = TBD
	#wind_dir = wind['deg']

	actual_str = actual_str + TEMP_SCALE # remove unneeded trailing data and append temperature scale (C or F) to the end
	feels_like_str = fl_str + TEMP_SCALE # remove unneeded trailing data and append temperature scale (C or F) to the end
	if DEBUG:
		print("Actual str: ", actual_str)
		print("Feels like str: ", feels_like_str)
	return;
# 
# draw_kr_pulse(position, direction) - draws a Knight Rider-style pulsing pixel. I put this in so that I could tell that the app was running, since weather
# 	data sometimes doesn't change very frequently. Plus it's cool. In a geeky sort of way. :-)
#
# 	position = 1,2,3,4,5 (eg which position on the line you want to illuminate)
#	direction = -1,1 (-1 = left, 1 = right). This is used so we know which previous pixel to turn off
#
def draw_kr_pulse(pos,dir):
	# clear 5 pixel line (easier than keeping track of where the previous illuminated pixel was)
	scrollphathd.clear_rect(12,5,5,1)
	x = pos + 11 #increase position to the actual x offset we need
	scrollphathd.set_pixel(x, 5, 0.2) #turn on the current pixel
	scrollphathd.show()
	time.sleep(KR_PULSE_DELAY)

	return;
#
# draw_temp_trend(dir)
# Draws an up arrow, down arrow, or equal sign on the rightmost 3 pixels of the display. Also show wind speed/gusts as a bar on the bottom.
#	dir = 0 (equal), 1 (increasing), -1 (decreasing)
#
def draw_temp_trend(dir):

	if dir == 0: #equal - don't display anything. Clear the area where direction arrow is shown
		scrollphathd.clear_rect(14,0,3,6)
	elif dir == 1: #increasing = up arrow. Draw an up arrow symbol on the right side of the display
		for y in range(0,5):
			scrollphathd.set_pixel(15,y,BRIGHT) #draw middle line of arrow
		scrollphathd.set_pixel(14,1,BRIGHT) #draw the 'wings' of the arrow
		scrollphathd.set_pixel(16,1,BRIGHT) 
	elif dir == -1: #decreasing = down arrow
		for y in range(0,5):
			scrollphathd.set_pixel(15,y,BRIGHT) #draw middle line of arrow
		scrollphathd.set_pixel(14,3,BRIGHT)
		scrollphathd.set_pixel(16,3,BRIGHT)

	return;

#
# draw_wind_line() - draws a single line indicator of wind speed and wind gusts on the bottom of the display
# Current wind speed is shown as as bright line and gusts as as dim line. 
#
# Calculation: calculate a ratio (17 pixels / max wind speed) and multiply by actual wind speed, rounding
#	to integer, yielding the number of pixels on 'x' axis to illuminate. 
 
def draw_wind_line():
	global wind_speed
	global wind_gusts
	wind_multiplier = (17.0 / MAX_WIND_SPEED)
	if DEBUG:
		print("Wind multiplier: ", wind_multiplier)
	wind_calc = wind_multiplier * wind_speed
	if DEBUG:
		print("wind calc: ", wind_calc)
	wind_calc = int(wind_calc) #convert to int
	if wind_calc > 17: #just in case something goes haywire, like a hurricane :-)
		wind_calc = 17
	gust_calc = wind_multiplier * wind_gusts
	if DEBUG:
		print("gust calc: ", gust_calc)
	gust_calc = int(gust_calc)
	if gust_calc > 17:
		gust_calc = 17
	if DEBUG:
		print("Wind speed, calc", wind_speed, wind_calc)
		print("wind gusts, calc", wind_gusts , gust_calc)
	# Draw the wind speed first
	for x in range(0,wind_calc):
		scrollphathd.set_pixel(x, 6, WIND_BRIGHTNESS)
	# Now draw the gust indicator as a single pixel	
	if gust_calc: #only draw if non zero
		scrollphathd.set_pixel(gust_calc-1, 6, GUST_BRIGHTNESS)
	return;

#
#
# display_temp_value(which_temp)
#
# This module allows the user to specify if they want actual or "feels like" temperature displayed. Feels like includes things like wind and humidity.
# which_temp = ACTUAL or FEELS_LIKE
#
def display_temp_value():
	global actual_str
	global feels_like_str
	# clear the old temp reading. If temp > 100 then clear an extra digit's worth of pixels
	if current_temp < 100:
		scrollphathd.clear_rect(0, 0, 12, 5)
	else:
		scrollphathd.clear_rect(0, 0, 17, 5)
	if CURRENT_TEMP_DISPLAY == 1: # show actual temp
		scrollphathd.write_string(actual_str, x = 0, y = 0, font = font3x5, brightness = BRIGHT)
	else:	#show feels_like temp
		scrollphathd.write_string(feels_like_str, x = 0, y = 0, font = font3x5, brightness = BRIGHT)
	scrollphathd.show()
	time.sleep(1)
	return;

# BEGIN MAIN LOGIC

print("'Live' temperature and wind display using National Weather Service API.")
print("Uses Raspberry Pi-W and Scrollphathd display. Written by Scott Hoge, November 2021")
print("Press Ctrl-C to exit")
print( "Current weather station: " , WEATHER_STATION)

# Initial weather data poll and write to display
get_weather_data()
display_temp_value() #change this to ACTUAL at the top if you want to display actual temp instead of feels like temp

draw_wind_line()

#
# Loop forever until user hits Ctrl-C
#

while True:
	if not (int(time.time()) % POLL_INTERVAL):
		prev_temp = current_temp
		get_weather_data()
		scrollphathd.clear()
		draw_wind_line()
		if current_temp < average_temp and (current_temp < 100 or current_temp < -9): #don't show temp trend arrow if > 100 degrees or < -10 degrees -- not enough room on the display.
			if DEBUG:
				print(time.asctime(time.localtime(time.time())), "Actual temp", actual_str, "Feels like temp", feels_like_str, "-")
			draw_temp_trend(-1)
		elif current_temp == average_temp and (current_temp < 100 or current_temp < -9):
			if DEBUG:
				print(time.asctime(time.localtime(time.time())), "Actual temp", actual_str, "Feels like temp", feels_like_str, "=")
			draw_temp_trend(0)
		elif current_temp > average_temp and (current_temp < 100 or current_temp < -9):
			if DEBUG:
				print(time.asctime(time.localtime(time.time())), "Actual temp", actual_str, "Feels like temp", feels_like_str, "+")
			draw_temp_trend(1)
		display_temp_value() #if you want actual temp, just change to ACTUAL

	# Pulse a pixel, Knight Rider style, just to show that everything is alive and working. Sleeps also keep Python from consuming 100% CPU
	# Use line 5, 14-17
	for pulse in range(1,5):
		draw_kr_pulse(pulse,1) #left to right
	for pulse in range(5,1,-1):
		draw_kr_pulse(pulse,-1) #back the other way

#termination code; clear the display
scrollphathd.clear()
scrollphathd.show()
print("Exiting....")
