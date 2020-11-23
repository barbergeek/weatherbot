# weatherbot
Pimoroni Scrollphathd-based weather display

https://github.com/pimoroni/scroll-phat-hd

Original version by Mark Ehr, 1/12/18. Released to the public domain with no warranties expressed or implied. Or something along those lines. Feel free to use
this code any way that you'd like. If you want to give me credit, that's great.

OWM version by Scott Hoge, 11/23/2020. Ditto the above. :-)

# Installation notes:
	# sudo pip3 install pyowm
    
	Then, do one of the following:
	# sudo apt-get install python3-scrollphathd 
	# sudo pip3 install scrollphat
	# curl https://get.pimoroni.com/scrollphathd | bash
	
	The scrollphat requires I2C enabled. Make sure that is turned on in raspi-config if the install above doesn't enable it.
	You will need an OpenWeather API key, available for free at <https://openweathermap.org>.
	You just need a free "Current Weather Data" subscription, not one of the paid ones, though you're welcome to support them.
	
	export OWM_API_KEY with your API key in your .bashrc (export OWM_API_KEY <OWM API key value>)

Note: if you want this to auto-run upon boot, add this line to the bottom of /etc/rc.local just above the "exit 0" line:  
\# sudo python3 {path}/owm-weatherbot.py &
