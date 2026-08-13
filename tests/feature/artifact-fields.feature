Feature: Attaching an artifact resolves internal and kind fields
  `lc attach` resolves two fields once, at the point of attachment, and both are read
  back exactly as resolved - never re-inferred from the artifact's value. `kind` says
  which viewer opens the artifact; `internal` says whether it counts as human-facing
  content.

  Background:
    Given a flow where the coder builds and the reviewer reviews
    And the item "specs/login.md" is filed at step "build"

  Scenario Outline: An undeclared kind defaults from the artifact's type
    When I attach a "<type>" artifact "some-value" to the item
    Then the attached artifact has kind "<kind>"

    Examples:
      | type     | kind     |
      | pr       | url      |
      | spec     | filepath |
      | brief    | filepath |
      | repo     | text     |
      | branch   | text     |
      | resolves | text     |

  Scenario: An explicitly declared kind overrides the type default
    When I attach a "pr" artifact "some-value" to the item with kind "text"
    Then the attached artifact has kind "text"

  Scenario: An artifact attached without the internal flag is not internal
    When I attach a "pr" artifact "some-value" to the item
    Then the attached artifact is not internal

  Scenario: An artifact attached with the internal flag is internal
    When I attach a "pr" artifact "some-value" to the item with the internal flag
    Then the attached artifact is internal
