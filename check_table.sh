#!/bin/bash
PGPASSWORD='jk_deploy_2026' psql -h 172.19.96.182 -U deploy -d jinkuaicha -c '\d fund_est_nav'
