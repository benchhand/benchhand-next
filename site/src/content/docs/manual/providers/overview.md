---
title: What providers are
description: The provider interface that kernels, FreeCAD, solvers, renderers, checks and storage plug into.
sidebar:
  order: 1
phase: 4
---

The [provider protocol](/reference/contracts/provider-protocol/) is the contract between benchhand and a provider.

## The provider kinds

Kernels, the CAD application, solvers, the renderer and viewers, process checks, artifact storage and policy.

## How a provider runs

Each provider is an out-of-process JSON-RPC 2.0 plugin in its own environment, with progress and artifact messages.

## What the server does with them

How the MCP server starts provider workers and runs their jobs.
