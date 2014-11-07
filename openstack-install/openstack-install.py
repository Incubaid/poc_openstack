#!/usr/bin/env python
__author__ = 'Mahmoud Adel <mahmoud@codescalers.com>'

import fabric.api as fabric
import uuid
import shutil
import re

#Setting variables
controllernode = '10.0.3.2'
computenode = '192.168.103.140'
networknode = '10.0.3.66'
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
    if 'RABBIT_PASS' not in globals():
        global RABBIT_PASS
        RABBIT_PASS = genpass()
    if 'METADATA_SECRET' not in globals():
        global METADATA_SECRET
        METADATA_SECRET = genpass()
    initprerequisites = (
        'grep -q %s /etc/hosts || echo "%s	controller" >> /etc/hosts' % (controllernode, controllernode),
        'apt-get update',
        'apt-get -y install python-software-properties software-properties-common',
        'add-apt-repository -y cloud-archive:juno',
        'apt-get update && apt-get -y dist-upgrade',
        'apt-get -y install rabbitmq-server',
        'rabbitmqctl change_password guest %s' % (RABBIT_PASS)
    )
    execute(node, initprerequisites)

def installkeystone(node):
    installprerequisites(node)
    global ADMIN_PASS
    global EMAIL_ADDRESS
    keystonecleanup = (
        'apt-get -y purge keystone',
        'rm -rvf /var/lib/keystone /etc/keystone'
    )
    KEYSTONE_DBPASS = genpass()
    keystoneinit = (
        'apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install mysql-server python-mysqldb keystone python-keystoneclient',
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
        'su -s /bin/sh -c "keystone-manage db_sync" keystone',
        '''(crontab -l -u keystone 2>&1 | grep -q token_flush) || \
      echo "@hourly /usr/bin/keystone-manage token_flush >/var/log/keystone/keystone-tokenflush.log 2>&1" \
      >> /var/spool/cron/crontabs/keystone'''
    )
    ADMIN_TOKEN = genpass()
    ADMIN_PASS = genpass()
    EMAIL_ADDRESS = 'support@mothership1.com'
    DEMO_PASS = genpass()
    copytemplate('controllernode/keystone.conf.template', 'controllernode/keystone.conf')
    sed('ADMIN_TOKEN', ADMIN_TOKEN, 'controllernode/keystone.conf')
    sed('KEYSTONE_DBPASS', KEYSTONE_DBPASS, 'controllernode/keystone.conf')
    execute(node, keystonecleanup)
    execute(node, ['mkdir -p /etc/keystone/'])
    upload(node, 'controllernode/keystone.conf', '/etc/keystone/keystone.conf')
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
        'rm -rvf /var/lib/keystone/keystone.db',
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
        'apt-get -y purge glance',
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
        'apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install glance python-glanceclient',
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
    copytemplate('controllernode/glance-api.conf.template', 'controllernode/glance-api.conf')
    sed('GLANCE_DBPASS', GLANCE_DBPASS, 'controllernode/glance-api.conf')
    sed('GLANCE_PASS', GLANCE_PASS, 'controllernode/glance-api.conf')
    upload(node, 'controllernode/glance-api.conf', '/etc/glance/glance-api.conf')
    copytemplate('controllernode/glance-registry.conf.template', 'controllernode/glance-registry.conf')
    sed('GLANCE_DBPASS', GLANCE_DBPASS, 'controllernode/glance-registry.conf')
    sed('GLANCE_PASS', GLANCE_PASS, 'controllernode/glance-registry.conf')
    upload(node, 'controllernode/glance-registry.conf', '/etc/glance/glance-registry.conf')
    execute(node, glanceinit, OS_TENANT_NAME='admin', OS_USERNAME='admin', OS_PASSWORD=ADMIN_PASS, OS_AUTH_URL='http://controller:35357/v2.0')

def installnova(node):
    global NOVA_PASS
    global NEUTRON_PASS
    NOVA_DBPASS = genpass()
    NOVA_PASS = genpass()
    NEUTRON_PASS = genpass()
    novacleanup = (
        'apt-get purge -y nova-api nova-cert nova-conductor nova-consoleauth nova-novncproxy nova-scheduler nova-common',
        'rm -rvf /var/lib/nova/CA/private'
    )
    novainit = (
        '''mysql -u root -e "
        DROP DATABASE IF EXISTS nova; \
        CREATE DATABASE nova; \
        GRANT ALL PRIVILEGES ON nova.* TO 'nova'@'localhost' \
        IDENTIFIED BY '%s'; \
        GRANT ALL PRIVILEGES ON nova.* TO 'nova'@'%s' \
        IDENTIFIED BY '%s'; \
        "
        ''' % (NOVA_DBPASS, '%', NOVA_DBPASS),
        'keystone user-create --name nova --pass %s' % (NOVA_PASS),
        'keystone user-role-add --user nova --tenant service --role admin',
        'keystone service-create --name nova --type compute --description "OpenStack Compute"',
        '''keystone endpoint-create \
  --service-id $(keystone service-list | awk '/ compute / {print $2}') \
  --publicurl http://controller:8774/v2/%\(tenant_id\)s \
  --internalurl http://controller:8774/v2/%\(tenant_id\)s \
  --adminurl http://controller:8774/v2/%\(tenant_id\)s \
  --region regionOne'''
    )
    execute(node, novacleanup)
    copytemplate('controllernode/nova.conf.template', 'controllernode/nova.conf')
    sed('NOVA_DBPASS', NOVA_DBPASS, 'controllernode/nova.conf')
    sed('RABBIT_PASS', RABBIT_PASS, 'controllernode/nova.conf')
    sed('NOVA_PASS', NOVA_PASS, 'controllernode/nova.conf')
    sed('NEUTRON_PASS', NEUTRON_PASS, 'controllernode/nova.conf')
    sed('CONTROLLER_IP', controllernode, 'controllernode/nova.conf')
    sed('METADATA_SECRET', METADATA_SECRET, 'controllernode/nova.conf')
    execute(node, ['mkdir -p /etc/nova/'])
    upload(node, 'controllernode/nova.conf', '/etc/nova/nova.conf')
    novaadd = (
        'apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" nova-api nova-cert nova-conductor nova-consoleauth nova-novncproxy nova-scheduler python-novaclient',
        'su -s /bin/sh -c "nova-manage db sync" nova',
        'service nova-api restart',
        'service nova-cert restart',
        'service nova-consoleauth restart',
        'service nova-scheduler restart',
        'service nova-conductor restart',
        'service nova-novncproxy restart',
        'rm -f /var/lib/nova/nova.sqlite'
    )
    execute(node, novainit + novaadd, OS_TENANT_NAME='admin', OS_USERNAME='admin', OS_PASSWORD=ADMIN_PASS, OS_AUTH_URL='http://controller:35357/v2.0')

def installnovacompute(node):
    installprerequisites(node)
    novacomputecleanup = (
        'apt-get -y purge nova-compute sysfsutils',
    )
    novacomputeadd = (
        'apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install nova-compute sysfsutils',
        'service nova-compute restart',
        '''echo "export OS_TENANT_NAME=admin
export OS_USERNAME=admin
export OS_PASSWORD=%s
export OS_AUTH_URL=http://controller:35357/v2.0" > /root/admin-openrc.sh''' % (ADMIN_PASS)
    )
    copytemplate('computenode/nova.conf.template', 'computenode/nova.conf')
    sed('RABBIT_PASS', RABBIT_PASS, 'computenode/nova.conf')
    sed('NOVA_PASS', NOVA_PASS, 'computenode/nova.conf')
    sed('COMPUTE_IP', computenode, 'computenode/nova.conf')
    execute(node, novacomputecleanup)
    execute(node, ['mkdir -p /etc/nova/'])
    upload(node, 'computenode/nova.conf', '/etc/nova/nova.conf')
    upload(node, 'computenode/nova-compute.conf.template', '/etc/nova/nova-compute.conf')
    execute(node, novacomputeadd)

def installneutroncontroller(node):
    NEUTRON_DBPASS = genpass()
    neutroncleanup = (
        'apt-get -y purge neutron-server neutron-plugin-ml2',
    )
    neutroninit = (
        '''mysql -u root -e "
        DROP DATABASE IF EXISTS neutron; \
        CREATE DATABASE neutron; \
        GRANT ALL PRIVILEGES ON neutron.* TO 'neutron'@'localhost' \
        IDENTIFIED BY '%s'; \
        GRANT ALL PRIVILEGES ON neutron.* TO 'neutron'@'%s' \
        IDENTIFIED BY '%s'; \
        "
        ''' % (NEUTRON_DBPASS, '%', NEUTRON_DBPASS),
        'keystone user-create --name neutron --pass %s' % (NEUTRON_PASS),
        'keystone user-role-add --user neutron --tenant service --role admin',
        'keystone service-create --name neutron --type network --description "OpenStack Networking"',
        '''keystone endpoint-create \
  --service-id $(keystone service-list | awk '/ network / {print $2}') \
  --publicurl http://controller:9696 \
  --adminurl http://controller:9696 \
  --internalurl http://controller:9696 \
  --region regionOne''',
        'apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install neutron-server neutron-plugin-ml2 python-neutronclient',
        'su -s /bin/sh -c "neutron-db-manage --config-file /etc/neutron/neutron.conf --config-file /etc/neutron/plugins/ml2/ml2_conf.ini upgrade juno" neutron',
        'service nova-api restart',
        'service nova-scheduler restart',
        'service nova-conductor restart',
        'service neutron-server restart'
    )
    execute(node, neutroncleanup)
    copytemplate('controllernode/neutron.conf.template', 'controllernode/neutron.conf')
    sed('NEUTRON_DBPASS', NEUTRON_DBPASS, 'controllernode/neutron.conf')
    sed('RABBIT_PASS', RABBIT_PASS, 'controllernode/neutron.conf')
    sed('NEUTRON_PASS', NEUTRON_PASS, 'controllernode/neutron.conf')
    with fabric.hide('running', 'output'):
        fabric.env.host_string = node
        SERVICE_TENANT_ID = fabric.run("source /root/admin-openrc.sh && keystone tenant-get service | grep id | awk '{print $4}'")
    sed('SERVICE_TENANT_ID', SERVICE_TENANT_ID, 'controllernode/neutron.conf')
    sed('NOVA_PASS', NOVA_PASS, 'controllernode/neutron.conf')
    execute(node, ['mkdir -p /etc/neutron/plugins/ml2/'])
    upload(node, 'controllernode/neutron.conf', '/etc/neutron/neutron.conf')
    upload(node,'controllernode/ml2_conf.ini.template', '/etc/neutron/plugins/ml2/ml2_conf.ini')
    execute(node, neutroninit, OS_TENANT_NAME='admin', OS_USERNAME='admin', OS_PASSWORD=ADMIN_PASS, OS_AUTH_URL='http://controller:35357/v2.0')

def installneutronnetwork(node):
    installprerequisites(node)
    neutroncleanup = (
        'apt-get -y purge neutron-plugin-ml2 neutron-plugin-openvswitch-agent neutron-l3-agent neutron-dhcp-agent',
    )
    with fabric.hide('running', 'output'):
        fabric.env.host_string = node
        INTERFACE_NAME = fabric.run("ip route show | grep 'default via' | awk '{print $5}'")
    neutroninit = (
        '''echo "net.ipv4.ip_forward=1
net.ipv4.conf.all.rp_filter=0
net.ipv4.conf.default.rp_filter=0" >> /etc/sysctl.conf''',
        'sysctl -p',
        'apt-get -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" install neutron-plugin-ml2 neutron-plugin-openvswitch-agent neutron-l3-agent neutron-dhcp-agent ethtool',
        'service openvswitch-switch restart',
        'ovs-vsctl add-br br-ex &',
        'ovs-vsctl add-port br-ex %s &' % (INTERFACE_NAME),
        'ethtool -K %s gro off' % (INTERFACE_NAME),
        'service neutron-plugin-openvswitch-agent restart',
        'service neutron-l3-agent restart',
        'service neutron-dhcp-agent restart',
        'service neutron-metadata-agent restart',
        '''echo "export OS_TENANT_NAME=admin
export OS_USERNAME=admin
export OS_PASSWORD=%s
export OS_AUTH_URL=http://controller:35357/v2.0" > /root/admin-openrc.sh''' % (ADMIN_PASS)
    )
    execute(node, neutroncleanup)
    copytemplate('networknode/neutron.conf.template', 'networknode/neutron.conf')
    sed('RABBIT_PASS', RABBIT_PASS, 'networknode/neutron.conf')
    sed('NEUTRON_PASS', NEUTRON_PASS, 'networknode/neutron.conf')
    execute(node, ['mkdir -p /etc/neutron/plugins/ml2/'])
    upload(node, 'networknode/neutron.conf', '/etc/neutron/neutron.conf')
    copytemplate('networknode/ml2_conf.ini.template', 'networknode/ml2_conf.ini')
    sed('INSTANCE_TUNNELS_INTERFACE_IP_ADDRESS', '10.10.110.1', 'networknode/ml2_conf.ini')
    upload(node, 'networknode/ml2_conf.ini', '/etc/neutron/plugins/ml2/ml2_conf.ini')
    upload(node, 'networknode/l3_agent.ini.template', '/etc/neutron/l3_agent.ini')
    upload(node, 'networknode/dhcp_agent.ini.template', '/etc/neutron/dhcp_agent.ini')
    copytemplate('networknode/metadata_agent.ini.template', 'networknode/metadata_agent.ini')
    sed('NEUTRON_PASS', NEUTRON_PASS, 'networknode/metadata_agent.ini')
    sed('METADATA_SECRET', METADATA_SECRET, 'networknode/metadata_agent.ini')
    execute(node, neutroninit)

def main():
    installkeystone(controllernode)
    installglance(controllernode)
    installnova(controllernode)
    installnovacompute(computenode)
    installneutroncontroller(controllernode)
    installneutronnetwork(networknode)

if __name__ == '__main__': main()
