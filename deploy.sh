#!/bin/bash
sudo docker stop hubspotcopilot
sudo docker rm hubspotcopilot
sudo docker build . -t netoai:hubspotcopilot-1
sudo docker run -itd --name hubspotcopilot --restart always -p 2095:2095 netoai:hubspotcopilot-1