$ORIGIN turkiyegundemi.com.
$TTL 300
@                IN SOA   ns1.turkiyegundemi.com. dns.turkiyegundemi.com. (
                              2026050502 ; serial
                              900        ; refresh
                              300        ; retry
                              1209600    ; expire
                              300        ; minimum
                         )
@                IN NS    ns1.turkiyegundemi.com.
@                IN NS    ns2.turkiyegundemi.com.
@                IN A     176.88.74.65
www              IN A     176.88.74.65
ns1              IN A     176.88.74.65
ns2              IN A     192.0.2.11
@                IN TXT   "v=spf1 -all"
_dmarc           IN TXT   "v=DMARC1; p=reject; adkim=s; aspf=s"
@                IN CAA   0 issue "letsencrypt.org"
