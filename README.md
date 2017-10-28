# Kubernetes -> Haproxy

Script em Python 3 que lê as mudanças de serviço da API do Kubernetes
para atualizar as configuração do HAProxy.

Procura pelo label "haproxy: true" em um serviço.
É necessário declarar o tipo da porta como **NodePort**.


**Pré-requisitos:**
- Python 3.6
    - Kubernetes API 4.0.0a
    - Jinja 2
- Kubernetes 1.8.1