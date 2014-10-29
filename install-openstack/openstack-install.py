#!/usr/bin/env python
__author__ = 'Mahmoud Adel <mahmoud@codescalers.com>'

import fabric.api as fabric
import uuid
import shutil
import re

#Setting variables
controllernode = '10.0.3.2'
networknode = ''
computenode = ''

#Setting functions
def execute(host, cmd):
    fabric.env.host_string = host
    for command in cmd:
        print fabric.run(command)

def upload(host, src, dst):
    fabric.env.host_string = host
    fabric.put(src, dst)

def genpass():
    randompass = str(uuid.uuid4()).replace("-","")
    return randompass

def copytemplate(src, dst):
    try:
        shutil.copy(src, dst)
    except:
        exit('Please make sure that configuration template exists!')

def sed(oldstr, newstr, infile):
    linelist = []
    with open(infile) as f:
        for item in f:
            newitem = re.sub(oldstr, newstr, item)
            linelist.append(newitem)
    with open(infile, "w") as f:
        f.truncate()
        for line in linelist: f.writelines(line)

def installkeystone():
    KEYSTONE_DBPASS = genpass()
    #Remarks: 
    #mysql binding address
    #keyston db sync after uploading conf
    keystonecmd = (
        'apt-get -y install mysql-server python-mysqldb keystone python-keystoneclient',
        '''mysql -u root -e "
        CREATE DATABASE keystone; \
        GRANT ALL PRIVILEGES ON keystone.* TO 'keystone'@'localhost' \
        IDENTIFIED BY '%s'; \
        GRANT ALL PRIVILEGES ON keystone.* TO 'keystone'@'%s' \
        IDENTIFIED BY '%s';
        "
        ''' % (KEYSTONE_DBPASS, '%', KEYSTONE_DBPASS),
        'echo "%s	controller" >> /etc/hosts' % (controllernode),
        'su -s /bin/sh -c "keystone-manage db_sync" keystone',
        '''(crontab -l -u keystone 2>&1 | grep -q token_flush) || \
      echo "@hourly /usr/bin/keystone-manage token_flush >/var/log/keystone/keystone-tokenflush.log 2>&1" \
      >> /var/spool/cron/crontabs/keystone'''
    )
    ADMIN_TOKEN = genpass()
    copytemplate('keystone.conf.template', 'keystone.conf')
    sed('ADMIN_TOKEN', ADMIN_TOKEN, 'keystone.conf')
    sed('KEYSTONE_DBPASS', KEYSTONE_DBPASS, 'keystone.conf')
    execute(controllernode, ['mkdir -p /etc/keystone/'])
    upload(controllernode, 'keystone.conf', '/etc/keystone/keystone.conf')
    execute(controllernode, keystonecmd)
    
installkeystone()    
