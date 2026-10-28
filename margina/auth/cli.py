from __future__ import annotations

import click
from flask.cli import AppGroup

from margina.auth.service import AuthServiceError, create_organization, create_user_with_membership

auth_cli = AppGroup("auth", help="Provision organizations and accounts without public registration.")


@auth_cli.command("create-organization")
@click.option("--tenant-id", required=True)
@click.option("--name", required=True)
@click.option("--currency", default="PKR", show_default=True)
@click.option("--timezone", "reporting_timezone", default="Asia/Karachi", show_default=True)
def create_organization_command(tenant_id: str, name: str, currency: str, reporting_timezone: str) -> None:
    try:
        organization = create_organization(tenant_id, name, currency, reporting_timezone)
    except AuthServiceError as error:
        raise click.ClickException(error.message) from error
    click.echo(f"Created organization {organization.tenant_id}.")


@auth_cli.command("create-user")
@click.option("--email", required=True)
@click.password_option(confirmation_prompt=True)
@click.option("--tenant-id", required=True)
@click.option(
    "--role",
    required=True,
    type=click.Choice(["administrator", "finance", "operations", "analyst"], case_sensitive=True),
)
@click.option("--branch", "branches", multiple=True, help="Repeat to restrict access; omit for all branches.")
def create_user_command(email: str, password: str, tenant_id: str, role: str, branches: tuple[str, ...]) -> None:
    try:
        account, membership = create_user_with_membership(email, password, tenant_id, role, branches)
    except AuthServiceError as error:
        raise click.ClickException(error.message) from error
    click.echo(f"Created user {account.email} with {membership.role} membership in {tenant_id}.")
