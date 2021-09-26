```
apt update
apt upgrade

cp /etc/apt/sources.list /etc/apt/sources.list.backup-buster
sed -i 's/buster\/updates/bullseye-security/g;s/buster/bullseye/g' /etc/apt/sources.list
apt update
apt upgrade
apt dist-upgrade

```

