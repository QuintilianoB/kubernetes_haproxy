# Kubernetes -> Haproxy
A script which read Kubernetes service's API and
update Haproxy config as it changes.

It watches for "haproxy: true" label in the service declaration.
The service type need to be a **NodePort**

Before start, you should set up ***database_config.yaml*** file.

**Dependencies:**
- Systemd SO
- Python 3.6
    - Kubernetes API 4.0.0a
    - Jinja 2
- Kubernetes 1.8.1.
- Kubernetes 1.8+ should work but I haven't tested it yet.

In the ***templates*** folder you can find a basic template for haproxy,
with or without SSL.

In the ***example*** folder there are pod/service declaration for kubernetes
wich work with this HAproxy integration.

#### Running
Just execute the script and tail the logs.
Should work as a systemd service as well.