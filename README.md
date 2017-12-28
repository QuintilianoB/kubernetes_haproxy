# Kubernetes -> Haproxy
A script which read Kubernetes service's API and
update Haproxy config as it changes.

It searchs for "haproxy: true" label in the service declaration.
The service type need to be a **NodePort**

Before start, you should set up ***config.yaml*** file.

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

If you set it on crontab, do as:
```
$ crontab -l
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
*  *  *  *  *  python3 /home/haproxy/client-python/haproxy_conf.py
```

@TODO
    - Instead of cron, use watch from k8s api.