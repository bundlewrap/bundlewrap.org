# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import datetime
from sys import exit

from ..concurrency import WorkerPool
from ..utils.cmdline import get_target_nodes
from ..utils.table import ROW_SEPARATOR, render_table
from ..utils.text import (
    blue,
    bold,
    error_summary,
    green,
    green_unless_zero,
    mark_for_translation as _,
    red,
    red_unless_zero,
    yellow,
    yellow_unless_zero,
)
from ..utils.time import format_duration
from ..utils.ui import io


def bw_apply(repo, args):
    errors = []
    target_nodes = get_target_nodes(repo, args['target'], adhoc_nodes=args['adhoc_nodes'])
    pending_nodes = target_nodes[:]

    repo.hooks.apply_start(
        repo,
        args['target'],
        target_nodes,
        interactive=args['interactive'],
    )

    start_time = datetime.now()
    results = []

    def tasks_available():
        return bool(pending_nodes)

    def next_task():
        node = pending_nodes.pop()
        return {
            'target': node.apply,
            'task_id': node.name,
            'kwargs': {
                'autoskip_selector': args['autoskip'],
                'force': args['force'],
                'interactive': args['interactive'],
                'workers': args['item_workers'],
                'profiling': args['profiling'],
            },
        }

    def handle_result(task_id, return_value, duration):
        if return_value is None:  # node skipped because it had no items
            return
        results.append(return_value)
        if args['profiling']:
            total_time = 0.0
            io.stdout(_("  {}").format(bold(task_id)))
            io.stdout(_("  {} BEGIN PROFILING DATA "
                        "(most expensive items first)").format(bold(task_id)))
            io.stdout(_("  {}    seconds   item").format(bold(task_id)))
            for time_elapsed, item_id in return_value.profiling_info:
                io.stdout("  {} {:10.3f}   {}".format(
                    bold(task_id),
                    time_elapsed.total_seconds(),
                    item_id,
                ))
                total_time += time_elapsed.total_seconds()
            io.stdout(_("  {} {:10.3f}   (total)").format(bold(task_id), total_time))
            io.stdout(_("  {} END PROFILING DATA").format(bold(task_id)))
            io.stdout(_("  {}").format(bold(task_id)))

    def handle_exception(task_id, exception, traceback):
        msg = "{}: {}".format(task_id, exception)
        io.stderr(traceback)
        io.stderr(repr(exception))
        io.stderr(msg)
        errors.append(msg)

    worker_pool = WorkerPool(
        tasks_available,
        next_task,
        handle_result=handle_result,
        handle_exception=handle_exception,
        pool_id="apply",
        workers=args['node_workers'],
    )
    worker_pool.run()

    total_duration = datetime.now() - start_time

    if args['summary'] and results:
        stats_summary(results, total_duration)
    error_summary(errors)

    repo.hooks.apply_end(
        repo,
        args['target'],
        target_nodes,
        duration=total_duration,
    )

    exit(1 if errors else 0)


def stats_summary(results, total_duration):
    totals = {
        'items': 0,
        'correct': 0,
        'fixed': 0,
        'skipped': 0,
        'failed': 0,
    }

    rows = [[
        bold(_("node")),
        _("items"),
        _("OK"),
        green(_("fixed")),
        yellow(_("skipped")),
        red(_("failed")),
        _("time"),
    ], ROW_SEPARATOR]

    for result in results:
        totals['items'] += len(result.profiling_info)
        for metric in ('correct', 'fixed', 'skipped', 'failed'):
            totals[metric] += getattr(result, metric)
        rows.append([
            result.node_name,
            str(len(result.profiling_info)),
            str(result.correct),
            green_unless_zero(result.fixed),
            yellow_unless_zero(result.skipped),
            red_unless_zero(result.failed),
            format_duration(result.duration),
        ])

    if len(results) > 1:
        rows.append(ROW_SEPARATOR)
        rows.append([
            bold(_("total ({} nodes)").format(len(results))),
            str(totals['items']),
            str(totals['correct']),
            green_unless_zero(totals['fixed']),
            yellow_unless_zero(totals['skipped']),
            red_unless_zero(totals['failed']),
            format_duration(total_duration),
        ])

    alignments = {
        1: 'right',
        2: 'right',
        3: 'right',
        4: 'right',
        5: 'right',
        6: 'right',
    }

    for line in render_table(rows, alignments=alignments):
        io.stdout("{x} {line}".format(x=blue("i"), line=line))
