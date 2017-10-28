#!/usr/bin/python3
# -*- coding: utf-8 -*-
from kubernetes import client, config
from jinja2 import Environment, FileSystemLoader, exceptions
from sys import exit
from subprocess import call, SubprocessError
from functools import partial
from shutil import copyfile
from os import path
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
            logging.error("Falha ao carregar arquivo de configuração: {}".format(error))
            exit(1)
        config.load_kube_config()
        self.services = []
        self.pool()
        self.controla_haproxy()

    def render_haproxy_cfg(self):
        try:
            env = Environment(loader=FileSystemLoader(self.path + self.conf['template_folder']), trim_blocks=True)
        except exceptions.TemplatesNotFound as error:
            logging.error("Pasta de templates não encontrada: {}".format(error))
        try:
            template = env.get_template(self.conf['haproxy_template'])
        except exceptions.TemplateNotFound as error:
            logging.error("Template {} não encontrado: {}".format(self.conf['haproxy_template'], error))
        try:
            output = template.render(services=self.services)
        except exceptions.TemplateRuntimeError as error:
            logging.error("Falha ao renderizar template {}: {}".format(self.conf['haproxy_template'], error))
        try:
            with open(self.path + self.conf['haproxy_temp_file'], 'w') as f:
                f.write(output)
        except EnvironmentError as error:
            logging.error("Falha ao salvar novo arquivo de configuração: {}".format(error))

    # Não verifico se o nome do serviço já existe pois o Kubernetes não aceita vários serviços com o mesmo nome.
    def pool(self):
        v1 = client.CoreV1Api()
        list = v1.list_service_for_all_namespaces(watch=False)
        for item in list.items:
            labels = item.metadata.labels
            ports = item.spec.ports
            # Os labels do Kubernetes são todos strings. Não é possível definir labels com True e False.
            if 'haproxy' in labels and labels['haproxy'] == 'true':
                info = {}
                info['name'] = item.metadata.name
                if labels['haproxy_port']:
                    info['haproxy_port'] = labels['haproxy_port']
                    backend = []
                    # Considero que o mesmo serviço pode responder para várias portas.
                    for port in ports:
                        backend.append({'port': port.node_port})
                    info['backend'] = backend
                else:
                    logging.error('Configurações para proxy reverso não encontradas no serviço {}. Verifique o YAML.'
                          .format(item.metadata.name))
                self.services.append(info)
        self.render_haproxy_cfg()

    def sha1sum(self, filename):
        with open(filename, mode='rb') as f:
            d = hashlib.sha1()
            for buf in iter(partial(f.read, 128), b''):
                d.update(buf)
        return d.hexdigest()

    def controla_haproxy(self):
        new_hash = self.sha1sum(self.path + self.conf['haproxy_temp_file'])
        cur_hash = self.sha1sum(self.conf['haproxy_conf_file'])
        if new_hash != cur_hash:
            copyfile(self.path + self.conf['haproxy_temp_file'], self.conf['haproxy_conf_file'])
            try:
                # Suprime a saída do HAProxy. Me interesso apenas pelo resultado final.
                saida = call(["haproxy", "-q","-c", "-f", self.conf['haproxy_conf_file']])
                if saida == 0:
                    call(["systemctl", "restart", "haproxy"])
                    logging.info("Haproxy reiniciado.")
                else:
                    logging.error("Erro na configuração do HAproxy.")
            except (TimeoutError, OSError, ValueError, SubprocessError) as error:
                logging.error("Falha ao reiniciar serviço: {}". format(error))


if __name__ == '__main__':
    HaproxyConfig()