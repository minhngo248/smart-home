# Step of installing on Pi
- Install Pi OS then flash into microSD
- Set PasswordAuthentication of sshd_config to `no`
- Install ufw, then allow port 22 and port 6443
- Install k3s (remember to allow cgroup then reboot)

# Install Mosquitto on K8s
## Self-signed certificate
- `allow_anonymous true`

```bash
# Publisher
docker run --rm -v ./certs/ca.crt:/ca.crt eclipse-mosquitto   mosquitto_pub -h local-pi -p 30883 --cafile /ca.crt -t /home/office/light -m "off"

# Subscriber
docker run --rm -v ./certs/ca.crt:/ca.crt eclipse-mosquitto   mosquitto_sub -h local-pi -p 30883 --cafile /ca.crt -t /home/office/light -v
```

# CPU Temp
```bash
vcgencmd measure_temp

# Max speed fan
sudo pinctrl set 45 a0

# Then reboot, fan will return to normal speed
sudo reboot
```