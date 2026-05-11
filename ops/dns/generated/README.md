# Generated DNS files

Zone: `turkiyegundemi.com`

Primary IPv4: `213.14.161.140`
Secondary IPv4: `213.14.161.140`

Copy `db.turkiyegundemi.com` to `/etc/bind/zones/db.turkiyegundemi.com` and include `named.conf.local` from BIND.

Registrar side needs glue/host records:

- `ns1.turkiyegundemi.com` -> `213.14.161.140`
- `ns2.turkiyegundemi.com` -> `213.14.161.140`

Then set domain nameservers to:

- `ns1.turkiyegundemi.com`
- `ns2.turkiyegundemi.com`
