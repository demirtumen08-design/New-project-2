$ORIGIN turkiyegundemi.com.
$TTL 300
@                IN SOA   ns1.turkiyegundemi.com. dns.turkiyegundemi.com. (
                              2026050812 ; serial
                              900        ; refresh
                              300        ; retry
                              1209600    ; expire
                              300        ; minimum
                         )
@                IN NS    ns1.turkiyegundemi.com.
@                IN NS    ns2.turkiyegundemi.com.
@                IN A     213.14.161.140
www              IN A     213.14.161.140
ns1              IN A     213.14.161.140
ns2              IN A     213.14.161.140
@                IN TXT   "v=spf1 -all"
_dmarc           IN TXT   "v=DMARC1; p=reject; adkim=s; aspf=s"
@                IN CAA   0 issue "letsencrypt.org"
