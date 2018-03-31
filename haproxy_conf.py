#!/usr/bin/python3
# -*- coding: utf-8 -*-
from kubernetes import client, config, watch
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

""" 
TODO - Console para lançar a execução manualmente, sem precisar usar o watcher.
TODO - Mudar a forma de lançar exceção. Não posso interromper a execução com o watcher.
TODO - Unificar as funções pool e watcher. Uma vem como objeto a outra como dict.
TODO - Utilizar pickle para armazenar o estado dos serviços. Criar uma blacklist de serviços com erro.
TODO - Adicionar um semáforo no watcher para evitar que, durante a criação de serviços instantaneamente consecutivos,
       o proxy reverso não precise ser reiniciado N vezes quanto N serviços criados.

Testes:
    - Serviço já existe quando o script ativa. OK
    - Criação de serviço com o script ativo. OK
    - Removação de serviço com o script ativo. OK
    - Erro na configuração de serviços:
        - Sem URL.
        - Com URL inválida.
        - Com nome de serviço errado.
        - Com nome de serviço duplicado.
    - Erro ao gravar arquivo do HAproxy.
    - Erro ao reiniciar o HAproxy.    
"""


class HaproxyConfig():
    def __init__(self):
        self.path = path.dirname(path.realpath(__file__)) + '/'
        logging.basicConfig(filename=path.dirname(path.realpath(__file__)) + '/client-python.log', level=logging.INFO,
                            format='%(asctime)s - %(levelname)s - %(message)s')

        try:
            self.conf = yaml.load(open(self.path + 'database_config.yaml'))
        except (OSError, IOError) as error:
            logging.error("Failed at load config file: {}".format(error))
            exit(1)

        config.load_kube_config()
        self.v1 = client.CoreV1Api()
        self.services = {}

        try:
            self.pool()
        except ValueError as error:
            logging.error(error)

        self.watcher()

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
                logging.info("New config file wrote")
        except EnvironmentError as error:
            logging.error("New haproxy config file could not be writen: {}".format(error))

        self.control()

    # Don't need to check if service already exist. K8s already do it.
    def pool(self):
        service_list = self.v1.list_service_for_all_namespaces(watch=False)
        for item in service_list.items:
            labels = item.metadata.labels
            # K8s's labels are only strings. Python's True/False may not be used.
            if 'haproxy' in labels and labels['haproxy'] == 'true' and item.spec.type == 'NodePort':
                if 'url' in labels.keys():
                    info = {}
                    info['url'] = labels['url']

                    # Each service can have more than one NodePort. It can create on backend for each but I ll lock it
                    # as one port per service. There are others problems if you choose to create multiple backends with
                    # only one service.
                    if len(item.spec.ports) == 1:
                        info['node_port'] = item.spec.ports[0].node_port
                        logging.info("Service {} found".format(item.metadata.name))
                    else:
                        error_message = 'More than one port was declared on {} service.'.format(item.metadata.name)
                        raise ValueError(error_message)

                    self.services[item.metadata.name] = info

        self.render_haproxy_cfg()

    # https://github.com/kubernetes-incubator/client-python
    # Almost identical to pool function. The problem is: Pool uses objects from kubernetes API and Watcher uses a dict.
    def watcher(self):
        w = watch.Watch()
        # We will watch for every service, regardless of namespaces. It's easier when mantaining a lot of pods
        # with a namespace for each.
        for event in w.stream(self.v1.list_service_for_all_namespaces):
            labels = event['raw_object']['metadata']['labels']
            item = event['raw_object']['spec']
            if 'haproxy' in labels and labels['haproxy'] == 'true' and item['type'] == 'NodePort':
                if 'url' in labels.keys():
                    info = {}
                    service_name = event['raw_object']['metadata']['name']
                    # If is a service inclusion and it doesn't existed when HAproxy started.
                    if event['type'] == 'ADDED':
                        if not service_name in self.services.keys():
                            info['url'] = labels['url']

                            if len(event['raw_object']['spec']['ports']) == 1:
                                info['node_port'] = event['raw_object']['spec']['ports'][0]['nodePort']
                                logging.info("Service {} included".format(service_name))
                            else:
                                error_message = 'More than one port was declared on {} service.'.format(service_name)
                                raise ValueError(error_message)

                            self.services[event['raw_object']['metadata']['name']] = info
                            self.render_haproxy_cfg()

                    elif event['type'] == 'DELETED':
                        if service_name in self.services.keys():
                            self.services.pop(service_name)
                            logging.info("Service {} removed".format(service_name))
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
            else:
                logging.info("Config file replaced.")
                self.restart()


if __name__ == '__main__':
    HaproxyConfig()