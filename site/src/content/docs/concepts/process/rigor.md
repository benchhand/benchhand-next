---
title: Rigor levels
description: How a project's rigor level adds requirements to its gates.
sidebar:
  order: 3
---

## The levels

A project has one of two rigor levels, set by `rigor` in [`hw/policy.yaml`](/concepts/policy/policy-yaml/):

- `standard`, the default. A project without `rigor`, or without a policy file, is at `standard`.
- `regulated`, which adds requirements to the gates.

```yaml
policy_version: 1
rigor: regulated
```

## What `regulated` adds

Under `regulated`, the requirements of the flow's rigor rule list apply as well as each gate's own requirements.

The rigor list is a [rule list](/concepts/policy/rule-lists/) whose output is a list of messages, one for each requirement that the record doesn't meet.
Its last choice gives `[]`: no unmet requirement.
Rigor holds only when the list of messages is empty, and each message tells you and the agent what is missing.

benchhand's own rigor list refuses a project-start setting that turns a check off.
The answers you give at INTENT are recorded as `flow.profile` in `hw/product.yaml`, and some of them can turn a check off, such as `stack_up: off` or `critique: off`.
At `standard`, those answers stand as recorded.
At `regulated`, such a setting is an unmet requirement.

A policy provider can add its own rigor list.
Every rigor list is evaluated, the providers' and the flow's, and rigor holds only when none of them gives a message.
A provider's list therefore only adds requirements, and never removes one of the flow's.
