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
def execute(host, cmd, **kwargs):
    fabric.env.host_string = host
    for command in cmd:
        with fabric.shell_env(**kwargs):
            fabric.run(command)

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
    keystonecleanup = (
        'rm -rvf /var/lib/keystone /etc/keystone',
        'apt-get -y purge keystone'
    )
    KEYSTONE_DBPASS = genpass()
    keystoneinit = (
        'apt-get -y install mysql-server python-mysqldb keystone python-keystoneclient',
        'sed /bind-address/d -i /etc/mysql/my.cnf',
        'service mysql restart',
        '''mysql -u root -e "
        DROP DATABASE IF EXISTS keystone; \
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
    ADMIN_PASS = genpass()
    EMAIL_ADDRESS = 'support@mothership1.com'
    DEMO_PASS = genpass()
    copytemplate('keystone.conf.template', 'keystone.conf')
    sed('ADMIN_TOKEN', ADMIN_TOKEN, 'keystone.conf')
    sed('KEYSTONE_DBPASS', KEYSTONE_DBPASS, 'keystone.conf')
    execute(controllernode, keystonecleanup)
    execute(controllernode, ['mkdir -p /etc/keystone/'])
    upload(controllernode, 'keystone.conf', '/etc/keystone/keystone.conf')
    execute(controllernode, keystoneinit)
    keystoneadd = (
        'keystone tenant-create --name admin --description "Admin Tenant"',
        'keystone user-create --name admin --pass %s --email %s' % (ADMIN_PASS, EMAIL_ADDRESS),
        'keystone role-create --name admin',
        'keystone user-role-add --tenant admin --user admin --role admin',
        'keystone user-role-add --tenant admin --user admin --role _member_',
        'keystone tenant-create --name demo --description "Demo Tenant"',
        'keystone user-create --name demo --pass %s --email %s' % (DEMO_PASS, EMAIL_ADDRESS),
        'keystone user-role-add --tenant demo --user demo --role _member_',
        'keystone tenant-create --name service --description "Service Tenant"',
        '''keystone service-create --name keystone --type identity \
  --description "OpenStack Identity"''',
        '''keystone endpoint-create \
  --service-id $(keystone service-list | awk '/ identity / {print $2}') \
  --publicurl http://controller:5000/v2.0 \
  --internalurl http://controller:5000/v2.0 \
  --adminurl http://controller:35357/v2.0 \
  --region regionOne'''
    )
    execute(controllernode, keystoneadd, OS_SERVICE_TOKEN=ADMIN_TOKEN, OS_SERVICE_ENDPOINT='http://controller:35357/v2.0')
    
installkeystone()    
