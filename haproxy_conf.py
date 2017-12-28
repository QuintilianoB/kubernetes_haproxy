#!/usr/bin/python3
# -*- coding: utf-8 -*-
from kubernetes import client, config
from jinja2 import Environment, FileSystemLoader, exceptions
from sys import exit
from subprocess import call, SubprocessError
from functools import partial
from shutil import copyfile
from os import path, mkdir
from datetime import datetime
from glob import glob
import yaml
import hashlib
import logging


class HaproxyConfig():
    def __init__(self):
        self.path = path.dirname(path.realpath(__file__)) + '/'
        logging.basicConfig(filename=path.dirname(path.realpath(__file__)) + '/client-python.log', level=logging.INFO,
                            format='%(asctime)s %(message)s')

        try:
            self.conf = yaml.load(open(self.path + 'config.yaml'))
        except (OSError, IOError) as error:
            logging.error("Failed at load config file: {}".format(error))
            exit(1)

        config.load_kube_config()
        self.services = []
        self.pool()
        self.control()

    def render_haproxy_cfg(self):
        try:
            env = Environment(loader=FileSystemLoader(self.path + self.conf['template_folder']), trim_blocks=True)
        except exceptions.TemplatesNotFound as error:
            logging.error("Template folder not found: {}".format(error))

        try:
            template = env.get_template(self.conf['haproxy_template'])
        except exceptions.TemplateNotFound as error:
            logging.error("Template {} not found: {}".format(self.conf['haproxy_template'], error))

        try:
            output = template.render(services=self.services)
        except exceptions.TemplateRuntimeError as error:
            logging.error("Fail to parse template {}: {}".format(self.conf['haproxy_template'], error))

        try:
            with open(self.path + self.conf['haproxy_temp_file'], 'w') as f:
                f.write(output)
        except EnvironmentError as error:
            logging.error("New haproxy config file could not be writen: {}".format(error))

    # Don't need to check if service already exist. K8s already do it.
    def pool(self):
        v1 = client.CoreV1Api()
        list = v1.list_service_for_all_namespaces(watch=False)

        for item in list.items:
            labels = item.metadata.labels
            ports = item.spec.ports
            # K8s's labels are only strings. Python's True/False may not be used.
            if 'haproxy' in labels and labels['haproxy'] == 'true':
                info = {}
                info['name'] = item.metadata.name
                if labels['haproxy_port']:
                    info['haproxy_port'] = labels['haproxy_port']
                    backend = []
                    # The same service can be listening in many ports.
                    for port in ports:
                        backend.append({'port': port.node_port})
                    info['backend'] = backend
                else:
                    logging.error('Could not find configs on Kubernetes services {}. Check your service declaration.'
                          .format(item.metadata.name))

                self.services.append(info)

        self.render_haproxy_cfg()

    def sha1sum(self, filename):
        with open(filename, mode='rb') as f:
            d = hashlib.sha1()
            for buf in iter(partial(f.read, 128), b''):
                d.update(buf)
        return d.hexdigest()

    def backup(self):
        date = datetime.now()
        filename = date.strftime('haproxy.cfg_%H_%M_%d%m%y')

        if not path.exists(self.path + 'backup'):
            mkdir(self.path + 'backup')

        try:
            copyfile(self.conf['haproxy_conf_file'], self.path + 'backup/' + filename)
        except EnvironmentError as error:
            logging.error("Unable to backup haproxy.cfg: {}".format(error))
        else:
            logging.info("Backup created {}".format(filename))

    def restore(self):
        files = glob('backup/haproxy.cfg*')
        newest_file = max(files, key=path.getctime)

        try:
            copyfile(self.path + newest_file, self.conf['haproxy_conf_file'])
        except EnvironmentError as error:
            logging.error("Unable to restore haproxy.cfg: {}".format(error))
        else:
            logging.info("Restored {}".format(newest_file))

    def restart(self):
        # Supress HAProxy output. Only need the exit status.
        saida = call(["haproxy", "-q", "-c", "-f", self.conf['haproxy_conf_file']])

        if saida == 0:
            try:
                call(["systemctl", "restart", "haproxy"])
            except (TimeoutError, OSError, ValueError, SubprocessError) as error:
                logging.error("Restart failed: {}".format(error))
                self.restore()
                self.restart()
            else:
                logging.info("Haproxy restarted successfuly.")
        else:
            logging.error("Problems found on haproxy.cfg")
            self.restore()

    def control(self):
        new_hash = self.sha1sum(self.path + self.conf['haproxy_temp_file'])
        cur_hash = self.sha1sum(self.conf['haproxy_conf_file'])

        if new_hash != cur_hash:
            self.backup()
            try:
                copyfile(self.path + self.conf['haproxy_temp_file'], self.conf['haproxy_conf_file'])
            except EnvironmentError as error:
                logging.error("Unable to replace haproxy.cfg: {}".format(error))
                exit(1)
            else:
                logging.info("New configuration file created.")
                self.restart()


if __name__ == '__main__':
    HaproxyConfig()