```
apt update
apt upgrade

sed -i 's/buster\/updates/bullseye-security/g;s/buster/bullseye/g' /etc/apt/sources.list
apt upgrade
apt dist-upgrade

```

