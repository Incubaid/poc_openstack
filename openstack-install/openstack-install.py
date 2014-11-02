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
credentials = list()

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

def installprerequisites(node):
    initprerequisites = (
        'apt-get update',
        'apt-get -y install python-software-properties software-properties-common',
        'add-apt-repository -y cloud-archive:juno',
        'apt-get update && apt-get -y dist-upgrade'
    )
    execute(node, initprerequisites)

def installkeystone(node):
    global ADMIN_PASS
    global EMAIL_ADDRESS
    keystonecleanup = (
        'rm -rvf /var/lib/keystone /etc/keystone /var/lib/keystone/keystone.db',
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
        'grep -q %s /etc/hosts || echo "%s	controller" >> /etc/hosts' % (node, node),
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
    execute(node, keystonecleanup)
    execute(node, ['mkdir -p /etc/keystone/'])
    upload(node, 'keystone.conf', '/etc/keystone/keystone.conf')
    execute(node, keystoneinit)
    keystoneadd = (
        'keystone tenant-create --name admin --description "Admin Tenant"',
        'keystone user-create --name admin --pass %s --email %s' % (ADMIN_PASS, EMAIL_ADDRESS),
        'keystone role-create --name admin',
        'keystone role-create --name _member_',
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
  --region regionOne''',
        '''echo "export OS_TENANT_NAME=admin
export OS_USERNAME=admin
export OS_PASSWORD=%s
export OS_AUTH_URL=http://controller:35357/v2.0" > /root/admin-openrc.sh''' % (ADMIN_PASS)
    )
    execute(node, keystoneadd, OS_SERVICE_TOKEN=ADMIN_TOKEN, OS_SERVICE_ENDPOINT='http://controller:35357/v2.0')

def installglance(node):
    GLANCE_DBPASS = genpass()
    GLANCE_PASS = genpass()
    glancecleanup = (
        'apt-get -y purge glance python-glanceclient',
    )

    glanceinit = (
        '''grep -q utf8 /etc/mysql/my.cnf || sed -i 's/\[mysqld\]/\[mysqld\]\\ncollation-server = utf8_general_ci\\ninit-connect = "SET NAMES utf8"\\ncharacter-set-server = utf8/g' /etc/mysql/my.cnf''',
        'service mysql restart',
        '''mysql -u root -e "
        DROP DATABASE IF EXISTS glance; \
        CREATE DATABASE glance; \
        GRANT ALL PRIVILEGES ON glance.* TO 'glance'@'localhost' \
        IDENTIFIED BY '%s'; \
        GRANT ALL PRIVILEGES ON glance.* TO 'glance'@'%s' \
        IDENTIFIED BY '%s'; \
        "
        ''' % (GLANCE_DBPASS, '%', GLANCE_DBPASS),
        'apt-get -y install glance python-glanceclient',
        'su -s /bin/sh -c "glance-manage db_sync" glance',
        'service keystone restart ; sleep 5',
        'keystone user-create --name glance --pass %s --email %s' % (GLANCE_PASS, EMAIL_ADDRESS),
        'keystone user-role-add --user glance --tenant service --role admin',
        'keystone service-create --name glance --type image --description "OpenStack Image Service"',
        '''keystone endpoint-create \
  --service-id $(keystone service-list | awk '/ image / {print $2}') \
  --publicurl http://controller:9292 \
  --internalurl http://controller:9292 \
  --adminurl http://controller:9292 \
  --region regionOne''',
        'service glance-registry restart',
        'service glance-api restart',
        'rm -f /var/lib/glance/glance.sqlite'
    )
    execute(node, glancecleanup)
    execute(node, ['mkdir -p /etc/glance/'])
    copytemplate('glance-api.conf.template', 'glance-api.conf')
    sed('GLANCE_DBPASS', GLANCE_DBPASS, 'glance-api.conf')
    sed('GLANCE_PASS', GLANCE_PASS, 'glance-api.conf')
    upload(node, 'glance-api.conf', '/etc/glance/glance-api.conf')
    copytemplate('glance-registry.conf.template', 'glance-registry.conf')
    sed('GLANCE_DBPASS', GLANCE_DBPASS, 'glance-registry.conf')
    sed('GLANCE_PASS', GLANCE_PASS, 'glance-registry.conf')
    upload(node, 'glance-registry.conf', '/etc/glance/glance-registry.conf')
    execute(node, glanceinit, OS_TENANT_NAME='admin', OS_USERNAME='admin', OS_PASSWORD=ADMIN_PASS, OS_AUTH_URL='http://controller:35357/v2.0')

def main():
    installprerequisites(controllernode)
    installkeystone(controllernode)
    installglance(controllernode)

if __name__ == '__main__': main()
