"""Tools for querying and managing Rucio replication rules."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import Context, FastMCP  # noqa: TC002

from rucio_mcp.tools._helpers import (
    build_hints,
    check_write_allowed,
    classify_error,
    format_dict,
    format_list,
    paginate_iter,
    parse_did,
)

_RULE_LIST_KEYS = [
    "id",
    "state",
    "rse_expression",
    "account",
    "copies",
    "expires_at",
    "locks_ok_cnt",
    "locks_replicating_cnt",
    "locks_stuck_cnt",
]

_RULE_INFO_KEYS = [
    "id",
    "state",
    "rse_expression",
    "account",
    "scope",
    "name",
    "copies",
    "bytes",
    "locks_ok_cnt",
    "locks_replicating_cnt",
    "locks_stuck_cnt",
    "error",
    "expires_at",
    "created_at",
    "updated_at",
]

_RULE_BYTE_KEYS = frozenset({"bytes"})


def register(mcp: FastMCP) -> None:
    """Register replication rule tools with the MCP server."""

    @mcp.tool()
    async def rucio_list_rules(
        did: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List all replication rules for a DID.

        Shows each rule's ID, state, RSE expression, account, copies requested,
        and expiry. Use this to understand where data is being replicated and
        whether rules are OK, REPLICATING, STUCK, or SUSPENDED.

        Args:
            did: The data identifier in ``scope:name`` format.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_did_rules(scope, name))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No replication rules found."

        hints = build_hints(
            ["Use `rucio_rule_info <rule_id>` to see full details of a specific rule"]
        )
        return (
            format_list(
                results, include_keys=_RULE_LIST_KEYS, byte_keys=_RULE_BYTE_KEYS
            )
            + hints
        )

    @mcp.tool()
    async def rucio_rule_info(
        rule_id: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show detailed information about a specific replication rule.

        Returns the full rule record including state, RSE expression, account,
        locks OK/REPLICATING/STUCK counts, error message (if any), and dates.

        Args:
            rule_id: The replication rule UUID
                (e.g. ``a1b2c3d4-e5f6-...``).
        """
        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            result = client.get_replication_rule(rule_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        state = result.get("state", "")
        did = f"{result.get('scope', '')}:{result.get('name', '')}"
        if state == "STUCK":
            hints = build_hints(
                [
                    "Rule is STUCK. Check if the destination RSE has capacity: "
                    f"`rucio_list_rse_usage {result.get('rse_expression', '<rse>')}`",
                    "Check the `error` field above for the specific failure reason",
                ]
            )
        elif state == "REPLICATING":
            hints = build_hints(
                [
                    f"Rule is still transferring. Check again with `rucio_rule_info {rule_id}`",
                    f"Use `rucio_list_dataset_replicas {did}` to see per-RSE progress",
                ]
            )
        elif state == "OK":
            hints = build_hints(
                [
                    f"Rule is complete. Use `rucio_list_dataset_replicas {did}` to verify replicas",
                ]
            )
        else:
            hints = build_hints(
                [f"Use `rucio_list_rules {did}` to see all rules for this DID"]
            )

        return (
            format_dict(result, include_keys=_RULE_INFO_KEYS, byte_keys=_RULE_BYTE_KEYS)
            + hints
        )

    @mcp.tool()
    async def rucio_list_rule_history(
        did: str,
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Show the full state history of all replication rules for a DID.

        Returns a chronological list of rule state transitions (OK, REPLICATING,
        STUCK, SUSPENDED, WAITING_APPROVAL, INJECT). Useful for auditing why
        a dataset ended up in its current replication state.

        Args:
            did: The data identifier in ``scope:name`` format.
            limit: Maximum number of history entries to return (default 50).
            offset: Number of entries to skip for pagination.
        """
        try:
            scope, name = parse_did(did)
        except ValueError as exc:
            return str(exc)

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            results = list(client.list_replication_rule_full_history(scope, name))
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No rule history found."

        page, footer = paginate_iter(iter(results), limit=limit, offset=offset)
        hints = build_hints(
            [
                f"Use `rucio_list_rules {did}` to see the current active rules for this DID"
            ]
        )
        return format_list(page) + footer + hints

    @mcp.tool()
    async def rucio_list_replication_rules(
        scope: str = "",
        account: str = "",
        limit: int = 50,
        offset: int = 0,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """List replication rules across all DIDs, optionally filtered.

        Unlike ``rucio_list_rules`` (which lists rules for a specific DID),
        this tool queries rules globally and can filter by scope or account.
        Useful for finding all rules owned by an account, or all rules for a
        given scope.

        Args:
            scope: Restrict to rules for DIDs in this scope
                (e.g. ``mc20_13TeV``). Omit to match all scopes.
            account: Restrict to rules owned by this account
                (e.g. ``gstark``). Omit to match all accounts.
            limit: Maximum number of rules to return (default 50).
            offset: Number of rules to skip for pagination.
        """
        filters: dict[str, Any] = {}
        if scope:
            filters["scope"] = scope
        if account:
            filters["account"] = account

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            it = client.list_replication_rules(filters=filters)
            results, footer = paginate_iter(it, limit=limit, offset=offset)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        if not results:
            return "No replication rules found."

        hints = build_hints(
            ["Use `rucio_rule_info <rule_id>` to see full details of a specific rule"]
        )
        return (
            format_list(
                results, include_keys=_RULE_LIST_KEYS, byte_keys=_RULE_BYTE_KEYS
            )
            + footer
            + hints
        )

    @mcp.tool()
    async def rucio_add_rule(
        dids: str,
        copies: int,
        rse_expression: str,
        lifetime: int = 0,
        grouping: str = "DATASET",
        locked: bool = False,
        source_replica_expression: str = "",
        notify: str = "N",
        activity: str = "",
        comment: str = "",
        ask_approval: bool = False,
        asynchronous: bool = False,
        delay_injection: int = 0,
        account: str = "",
        weight: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Create a new replication rule to copy data to an RSE.

        Submits a replication rule that instructs Rucio to ensure ``copies``
        copies of each DID exist at RSEs matching ``rse_expression``. Returns
        the new rule ID(s).

        Args:
            dids: One or more space-separated DIDs in ``scope:name`` format.
            copies: Number of copies to create at matching RSEs.
            rse_expression: Boolean RSE expression for the destination.
                Examples: ``CERN-PROD_DATADISK``, ``tier=1&country=US``.
            lifetime: Rule lifetime in seconds. 0 means no expiry.
            grouping: How to group files: ``DATASET`` (default), ``ALL``,
                or ``NONE``.
            locked: If True, the rule cannot be deleted.
            source_replica_expression: RSE expression for preferred source
                replicas during transfer.
            notify: Notification strategy: ``N`` (none), ``Y`` (yes),
                ``C`` (on close).
            activity: Transfer activity label (e.g. ``User``,
                ``Data Consolidation``).
            comment: Free-text comment attached to the rule.
            ask_approval: If True, submit the rule for admin approval rather
                than creating it immediately.
            asynchronous: If True, create the rule asynchronously.
            delay_injection: Seconds to wait before applying the rule (implies
                asynchronous).
            account: Account that owns the rule. Defaults to the authenticated
                account.
            weight: RSE weight attribute to use for replica selection.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        did_list = dids.split()
        parsed = []
        for did in did_list:
            try:
                scope, name = parse_did(did)
            except ValueError as exc:
                return str(exc)
            parsed.append({"scope": scope, "name": name})

        kwargs: dict[str, Any] = {"grouping": grouping, "notify": notify}
        if lifetime:
            kwargs["lifetime"] = lifetime
        if locked:
            kwargs["locked"] = locked
        if source_replica_expression:
            kwargs["source_replica_expression"] = source_replica_expression
        if activity:
            kwargs["activity"] = activity
        if comment:
            kwargs["comment"] = comment
        if ask_approval:
            kwargs["ask_approval"] = ask_approval
        if asynchronous:
            kwargs["asynchronous"] = asynchronous
        if delay_injection:
            kwargs["delay_injection"] = delay_injection
        if account:
            kwargs["account"] = account
        if weight:
            kwargs["weight"] = weight

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            rule_ids = client.add_replication_rule(
                parsed, copies, rse_expression, **kwargs
            )
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        rule_list = "\n".join(f"- `{rid}`" for rid in rule_ids)
        hints = build_hints(
            [
                f"Use `rucio_rule_info {rule_ids[0]}` to check rule status"
                if rule_ids
                else "Use `rucio_list_replication_rules` to find your rules"
            ]
        )
        return "**Created rule(s):**\n" + rule_list + hints

    @mcp.tool()
    async def rucio_delete_rule(
        rule_id: str,
        purge_replicas: bool = False,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Delete a replication rule.

        Removing a rule may cause replicas to be garbage-collected if no other
        rule protects them.

        Args:
            rule_id: The replication rule UUID to delete.
            purge_replicas: If True, immediately remove the replicas covered
                by this rule rather than waiting for the reaper.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            client.delete_replication_rule(rule_id, purge_replicas=purge_replicas)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            ["Use `rucio_list_rules <scope:name>` to verify the rule is gone"]
        )
        return f"Rule {rule_id} deleted." + hints

    @mcp.tool()
    async def rucio_update_rule(
        rule_id: str,
        lifetime: int = 0,
        locked: bool = False,
        comment: str = "",
        activity: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Update mutable fields on an existing replication rule.

        Only the fields you provide are changed; omitted fields are left as-is.
        Pass ``lifetime=0`` to leave the lifetime unchanged.

        Args:
            rule_id: The replication rule UUID to update.
            lifetime: New lifetime in seconds from now. 0 means no change.
            locked: Set the locked flag (True = cannot be deleted).
            comment: Replace the rule's comment.
            activity: Replace the transfer activity label.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        options: dict[str, Any] = {}
        if lifetime:
            options["lifetime"] = lifetime
        if locked:
            options["locked"] = locked
        if comment:
            options["comment"] = comment
        if activity:
            options["activity"] = activity

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            client.update_replication_rule(rule_id, options)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints([f"Use `rucio_rule_info {rule_id}` to verify the change"])
        return f"Rule {rule_id} updated." + hints

    @mcp.tool()
    async def rucio_reduce_rule(
        rule_id: str,
        copies: int,
        exclude_expression: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Reduce the number of copies in a replication rule.

        Rucio will remove replicas from RSEs to reach the new copy count,
        respecting any exclusion expression. Returns the ID of the replacement
        rule.

        Args:
            rule_id: The replication rule UUID to reduce.
            copies: New (lower) number of copies.
            exclude_expression: RSE expression for sites that must not lose
                replicas during the reduction.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            new_rule_id = client.reduce_replication_rule(
                rule_id, copies, exclude_expression=exclude_expression or None
            )
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_rule_info {new_rule_id}` to check the new rule status"]
        )
        return f"Rule reduced. New rule ID: {new_rule_id}" + hints

    @mcp.tool()
    async def rucio_move_rule(
        rule_id: str,
        rse_expression: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Move a replication rule to a different RSE expression.

        Creates a new rule at the target RSE expression and removes the
        original once transfers complete. Returns the new rule ID.

        Args:
            rule_id: The replication rule UUID to move.
            rse_expression: RSE expression for the new destination.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            new_rule_id = client.move_replication_rule(
                rule_id, rse_expression, override={}
            )
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_rule_info {new_rule_id}` to check the new rule status"]
        )
        return f"Rule moved. New rule ID: {new_rule_id}" + hints

    @mcp.tool()
    async def rucio_approve_rule(
        rule_id: str,
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Approve a replication rule that is waiting for approval.

        Only account managers and admins can approve rules. The rule must be
        in WAITING_APPROVAL state.

        Args:
            rule_id: The replication rule UUID to approve.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            client.approve_replication_rule(rule_id)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_rule_info {rule_id}` to see updated rule status"]
        )
        return f"Rule {rule_id} approved." + hints

    @mcp.tool()
    async def rucio_deny_rule(
        rule_id: str,
        reason: str = "",
        *,
        ctx: Context[Any, Any],
    ) -> str:
        """Deny a replication rule that is waiting for approval.

        Args:
            rule_id: The replication rule UUID to deny.
            reason: Optional reason for the denial, shown to the requester.
        """
        if err := check_write_allowed(ctx.request_context.lifespan_context):
            return err

        client = ctx.request_context.lifespan_context["rucio_client"]
        try:
            client.deny_replication_rule(rule_id, reason=reason or None)
        except Exception as exc:  # noqa: BLE001
            return classify_error(exc)

        hints = build_hints(
            [f"Use `rucio_rule_info {rule_id}` to see updated rule status"]
        )
        return f"Rule {rule_id} denied." + hints
