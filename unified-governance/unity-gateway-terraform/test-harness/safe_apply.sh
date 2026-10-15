#!/bin/bash
# usage: safe_apply.sh <allowed-address-regex> [terraform -var args...]
# Plans to a file, refuses any delete or any change outside the allowed addresses, then applies that plan.
set -e
ALLOW="$1"; shift
terraform plan -no-color -out=tf.plan "$@" > plan.log 2>&1 || { tail -20 plan.log; exit 1; }
terraform show -json tf.plan | python3 -c "
import json,sys,re
p=json.load(sys.stdin); bad=[]; n=0
for rc in p.get('resource_changes',[]):
    a=rc['change']['actions']
    if a in (['no-op'],['read']): continue
    n+=1
    if 'delete' in a or not re.search(sys.argv[1], rc['address']): bad.append((rc['address'],a))
print('planned changes:',n)
if bad:
    print('REFUSED:'); [print('  ',b) for b in bad]; sys.exit(1)
" "$ALLOW"
terraform apply -no-color tf.plan 2>&1 | grep -E 'Apply complete|Error'
