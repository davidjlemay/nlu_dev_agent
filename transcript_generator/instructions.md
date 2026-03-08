# Generic instructions for NLU implementation tasks

-   [Introduction](#GenericinstructionsforNLUimplementation)

-   [OneNLU vs CustomNLU vs.
    NCSref](#GenericinstructionsforNLUimplementation)

-   [Setup to use](#GenericinstructionsforNLUimplementation)

    -   [OneNLU setup](#GenericinstructionsforNLUimplementation)

    -   [CustomNLU setup (CustomNLU Embedded & CustomNLU
        Cloud)](#GenericinstructionsforNLUimplementation)

-   [Generic instructions per
    section](#GenericinstructionsforNLUimplementation)

    -   [Tech prime &
        reviewer](#GenericinstructionsforNLUimplementation)

    -   [Background](#GenericinstructionsforNLUimplementation)

    -   [Requirements](#GenericinstructionsforNLUimplementation)

    -   [Test plan](#GenericinstructionsforNLUimplementation)

    -   [Spec changes MRs](#GenericinstructionsforNLUimplementation)

    -   [System spec changes](#GenericinstructionsforNLUimplementation)

    -   [Signatures](#GenericinstructionsforNLUimplementation)

    -   [Minimal requirements](#GenericinstructionsforNLUimplementation)

    -   [Watch this ticket](#GenericinstructionsforNLUimplementation)

    -   [Create integration happy path
        tests](#GenericinstructionsforNLUimplementation)

        -   [Including happy paths in LA and
            regtests](#GenericinstructionsforNLUimplementation)

    -   [Gazetteers](#GenericinstructionsforNLUimplementation)

    -   [Canonicalization](#GenericinstructionsforNLUimplementation)

        -   [CF coverage
            testing](#GenericinstructionsforNLUimplementation)

    -   [ASR Datapatch generation and vocab
        update](#GenericinstructionsforNLUimplementation)

    -   [Language specific regex
        update](#GenericinstructionsforNLUimplementation)

    -   [Data cleaning](#GenericinstructionsforNLUimplementation)

        -   [Setting up the \$FASFILES
            variable](#GenericinstructionsforNLUimplementation)

    -   [Unit tests, JSGFs & coverage
        tests](#GenericinstructionsforNLUimplementation)

    -   [Backward compatibility
        mapping](#GenericinstructionsforNLUimplementation)

    -   [Staging and training
        configuration](#GenericinstructionsforNLUimplementation)

        -   [Add new JSGF/unit test intents in
            stage.stark](#GenericinstructionsforNLUimplementation)

        -   [Add new gazetteers to model
            training](#GenericinstructionsforNLUimplementation)

        -   [Extraction specs](#GenericinstructionsforNLUimplementation)

    -   [Run staging and training
        pipeline](#GenericinstructionsforNLUimplementation)

    -   [Generate new
        regtests](#GenericinstructionsforNLUimplementation)

    -   [Troubleshooting](#GenericinstructionsforNLUimplementation)

    -   [Test Plan](#GenericinstructionsforNLUimplementation)

        -   [Minimal testing](#GenericinstructionsforNLUimplementation)

        -   [Normal testing](#GenericinstructionsforNLUimplementation)

        -   [Additional/scrutiny
            testing](#GenericinstructionsforNLUimplementation)

    -   [Logging working hours in
        JIRA](#GenericinstructionsforNLUimplementation)

-   [Instructions for tech
    primes](#GenericinstructionsforNLUimplementation)

# Introduction

This page will contain all instructions for regular NLU implementation
tasks that remain the same across all tasks. It should be considered as
the stable backbone of instructions by default. Individual ONENLU epics
will progressively be trimmed down to only cover instructions that are
specific to the task itself, and will refer to this documentation for
the rest.

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Some particular implementation tasks may
be very different from usual and require totally custom instructions.
Instructions of such tasks will **explicitly** state that these generic
instructions should be ignored. Without this explicit override, this
documentation page will always remain the primary reference.

# OneNLU vs CustomNLU vs. NCSref

These instructions will cover implementation tasks both for cloud
(primarily for OneNLU and CustomNLU Cloud, since Legacy Cloud/NCSref is
now pretty much frozen) and embedded (OneNLU and CustomNLU), because
both types of tasks have a lot in common.

They do however have differences, e.g. different branch setup, cloud
having additional testing elements like regtests, etc.

To make the distinction easier, these instructions will color or frame
parts specific to cloud in orange, and those specific to embedded in
blue.

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}ONENLU epics have a \"Component/s\" field
which will indicate the type of task; cloud tasks have a value \"OneNLU
Cloud\" for CloudRef, \"CustomNLU Cloud\" for CustomNLU (aka
MercedesCloud) or \"Legacy Cloud\" for NCSref, while embedded tasks have
a \"OneNLU Embedded\" or \"CustomNLU Embedded\" (aka MercedesEmbedded).
If this field is missing or has all five values at once, ask the tech
prime to clarify (all components at once should never happen). If both
\"OneNLU Cloud\" and \"OneNLU Embedded\" (or both \"CustomNLU Cloud\"
and \"CustomNLU Embedded) are present, the task should be completed for
both cloud and embedded setups.

# Setup to use

### OneNLU setup

**Cloud**

For cloudref tasks, the setup depends on whether the tasks needs to be
done for a development stream that already has its milestone resources
branches forked or not:

-   If yes, e.g. if your task must be implemented in the 8.36.0 stream
    and the branch integration-\$lang_Cloud_Ref_8_36_0 (e.g.
    integration-it-IT_Cloud_Ref_8_36_0 for Italian) already exists in
    your language main resources, you must use this branch as target for
    your work.

    -   The target anno-lang branch has the same name,
        integration-\$lang_Cloud_Ref_8_5_0.

    -   The corresponding common-lang resources branch is
        Cloud_Ref_8_5_0.

-   If no, i.e. if the target stream is still the latest stream being
    developed, then the main resources language branch is integration.
    This should be the case for most cloud tasks.

    -   The target anno-lang branch is also integration.

    -   The corresponding common-lang resources branch is master.

For NCSref, milestone branch names are identical with \"NCS\" instead of
\"Cloud\" (e.g. integration-it-IT_NCS_Ref_8_36_0). All mainline branches
are called \"ncs_ref/v1\" (main resources, anno-lang and common-lang)

**Embedded**

For embedded tasks, the target main language resources branch is
\"EmbeddedRefDesign\" and the same branch name is used for common-lang
resources. The anno-lang branch is integration (shared with cloudref).

The common-lang milestone branch for embedded reference is currently
called \"ERD_release\" (overwritten every other week). A branch of that
name is also created in the language resources for each language,
although its creation/update might be scripted (TBC), and therefore this
should not be a common setup for feature development itself.

### CustomNLU setup (CustomNLU Embedded & CustomNLU Cloud)

if \'component=CustomNLU\*\' and \'label != NLU_Share \| CUSTOM_Share\'

-   this is CustomNLU specific work

-   work on Mercedes(anno) and
    MercedesEmbedded(resources)/MercedesCloud(resources)

if \'component=CustomNLU\*\' and \'label == NLU_Share 

-   this work is requested by CustomNLU but will be shared with OneNLU

-   work on Mercedes(anno) and
    MercedesEmbedded(resources)/MercedesCloud(resources)

-   then cherry pick the work to integration(anno) and
    EmbeddedRefDesign(resources)/integration(resources)

if \'component=CustomNLU\*\' and \'label == CUSTOM_Share 

-   this work is requested by OneNLU but will be shared with CustomNLU

-   work on integration(anno) and
    EmbeddedRefDesign(resources)/integration(resources)

-   then cherry pick the work to Mercedes(anno) and
    MercedesEmbedded(resources)/MercedesCloud(resources)

# Generic instructions per section

## Tech prime & reviewer

Gives the name of the tech prime who designed the task and the reviewer
who reviewed it.

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}When asking a question on the JIRA,
always quote the name of the tech prime (enter @ then find the user\'s
name) to make sure that they get notified of your question.

## Background

This section gives a summary explanation of the feature being
implemented in this task.

## Requirements

If present, this section typically contains pointers to other tickets
that triggered the task, e.g. User Stories, HDDD tickets.

## Test plan

This section will briefly describe the test plan of the task. Refer to
the section \"test plan\" section further below for the detailed generic
instructions.

## Spec changes MRs

Contains links to the changes to system specs, project specs and
common-lang resources MRs that were needed for the task (+ any moretools
MR if applicable).

## System spec changes

Summarizes in one or two tables main changes to the system/project
specs:

-   new, removed or renamed parsetypes and/or mentions;

-   new, removed or renamed slot types and/or canonicals.

## Signatures

Contains a list of system specs and anno specs signatures that were
added for this task, or were already present but are relevant for the
task. The list might be in the form of code snippets from
system_spec.json and anno_specs_signatures.json.

Optionally contains a description of the conversions between anno specs
and system specs if they are more complex than simple renamings.

## Minimal requirements

Some implementation tasks need to be partially completed as soon as the
specs changes are merged because they cause a failure of staging. If
this is the case, this section will list what these must-do changes are.

Typical cases:

-   When canonicals in an existing cano entity are renamed or deleted,
    resources must be immediately updated accordingly. (No immediate
    action is needed for new canonicals).

-   When a slot type canonicalized by phraselist is renamed or deleted,
    languages that assigned its dictionary explicitly in gazetteer.stark
    must update it accordingly. (No immediate action is needed for new
    cano entities).

-   When a parsetype or mention is renamed or deleted, data annotated in
    app specs that are used as sources for LA or cloud regtests, or are
    located in jiras_train or jiras_testonly, must be immediately
    updated accordingly.

    -   ![(warning)](media/image1.tmp){width="0.16666666666666666in"
        height="0.16666666666666666in"}**This include Topic lists**,
        since they are used as sources for LA, outdated annotations will
        cause LA staging failure.

        -   Since topic lists are periodically regenerated, consider to
            just remove lines with obsolete annotations rather than
            spending time to reannotate them manually, they will be
            restored with correct annotation at the next regeneration.

    -   ![(info)](media/image2.tmp){width="0.16666666666666666in"
        height="0.16666666666666666in"}No immediate action is needed for
        other app specs sources like special sets not used in LA or app
        specs corrections, they would not cause pipeline failures, but
        it\'s generally safer and easier to do all corrections at once
        (also to avoid checking which special sets are used in LA/GA and
        which ones aren\'t).

    -   ![(info)](media/image2.tmp){width="0.16666666666666666in"
        height="0.16666666666666666in"}For now invalid canonicalization
        within app specs annotations do not cause staging failures, but
        in the future this check will be enforced at some point.

-   When a new \"PHRASELIST-IF\" dictionary is added in tag value
    conversions, all languages need to declare a dictionary named
    \"PHRASELIST-IF.phraselist\" in their gazetteer.stark.

-   ![(warning)](media/image1.tmp){width="0.16666666666666666in"
    height="0.16666666666666666in"}When a gazetteer needs to be removed
    or renamed as part of a minimal requirement, then its reference
    needs to be updated in all relevant configuration files like
    gazetteer.stark, jsgf.stark, dictionaries.stark, grammar.json.

## Watch this ticket

This header is just a reminder to add yourself as a watcher on the
instructions ticket, so that you won\'t miss any updates in the
instructions, or relevant discussions in the comments.

To do so, please click on \"Start watching this issue\" in the
upper-right corner of the JIRA page.

## Create integration happy path tests

In most implementation tasks, in particular regular tasks for the
implementation of new features, we add some happy path utterances that
cover the feature being implemented in the task (typically one utterance
example per semantic signature, but it can vary).

Happy paths must follow these guidelines:

-   The filename must start with the \"HP\_\" prefix, then the ONENLU
    number of the epic, followed by some keywords that summarize the
    feature. **The exact filename to use will be provided in the epic
    instructions.**

-   **By default, since the setup change from
    [ONENLU-346302](https://cerence.atlassian.net/browse/ONENLU-346302) -
    Getting issue details\...** STATUS **, the HP file should be
    located:**

-   **in
    \$RESOURCES/\$lang/common-app/CTagger/data/cloud_regtest_jiras/jiras_train
    for cloud tasks**

-   **in \$RESOURCES/\$lang/common-app/CTagger/data/jiras_train for
    embedded tasks if you don\'t want the HP to be included in XML
    regtests (default); else use the cloud_regtest_jiras subdirectory if
    you want it to be included, for instance for the sake of CF coverage
    tests for tasks containing new canonicals.**

    -   ** If both embedded and cloud are listed as components for the
        task, then use the cloud_regtest_jiras subfolder by default,
        unless indicated otherwise.**

        -   ![(info)](media/image2.tmp){width="0.16666666666666666in"
            height="0.16666666666666666in"}Task instructions will
            generally mention which folder to use (i.e. whether
            inclusion in cloud XML regtests is recommended or not).

    -   ![(info)](media/image2.tmp){width="0.16666666666666666in"
        height="0.16666666666666666in"}Some tasks may request you to
        create the file in jiras_testonly rather than jiras_train, e.g.
        for features that are supported in literal and/or grammar
        annotator only.

-   Use natural, simple, common utterances without confusable
    pronunciation.

-   Cases should be non-ambiguous and not confusable with other NLU
    intents.

-   Cases should be localized (not only translated), i.e. any named
    entities should be replaced with entities that are still meaningful
    for the region(s) targeted by your language; a typical example is
    replacing names of US cities or businesses with cities or businesses
    from the regions of your language.

-   Make sure that HP mentions are self-consistent; e. g. \"find a cafe
    in avenue park\" can be used as happy path if a cafe exist in a
    street of that name, \"play umbrella by rihanna\" can be used
    because \"umbrella\" is really the name of a song performed by
    rihanna.

-   Make sure that HP tokenization/normalization matches what ASR will
    return.

Each task will contain the list of English example happy paths to
localize. To save time, we will use the anno guide annotation format
plus the target fieldID (ex. FieldID tab PT tab utterance with
\[mention\]\<mention\>). This will make localization faster since there
isn\'t a mention for each word. Then use
\$MORETOOLS/annotation/minify.py to convert to ordinary
fieldannotatedstring format. Example:

\$MORETOOLS/annotation/minify.py -i
tmp_input_file_with_localized_trs_format.txt -o
\$RESOURCES/\$lang/common-app/CTagger/data/jiras_train/HP_ONENLU-TICKET_NUMBER_AND_TOPIC.fieldannotatedstring
-c trs_to_as -b

Run python \$MORETOOLS/annotation/minify.py -h to see the explanations
of i/o-flags.

(Update on 2025/06/04) With the following command, you can fetch the
localizations from Guarded Utterances if they are already translated by
your team:

python3 \$MORETOOLS/langdev/gu_to_fas.py -t ONENLU-123456 -l LNG
\[\--gu_path /mnt/nlu/users/\$USER/guarded_utterances/gu_data\]

By default, the gu_data is fetched from
nlu/projects/here-work/resci/jenkins_nlu_models/PicklistAgent/workspace/guarded_utterances/NLUcoords_guarded_utterances_pipeline/gu_data,
which is updated more than once a day. If there are local changes in
your gu_data repo, the optional \--gu_path parameter can be defined.\
This command will create a text file called
\"{fas_name_from_ticket}.txt\" and a log file called
\"{fas_name_from_ticket}.log\". After checking the localizations and
translating any non-matches, run \$MORETOOLS/annotation/minify.py -i
{fas_name_from_ticket}.txt -o
{fas_name_from_ticket}.fieldannotatedstring -c trs_to_as -b to create
the annotated FAS file.

### Including happy paths in LA and regtests

We must always ensure that all happy path files are included as source
for the literal annotator (both in cloud and embedded) and for XML
regtests (in cloud only, and only mandatory for happy paths of cloud
tasks).

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}For embedded tasks, unless indicated
otherwise, adding the HP to the cloud LA is optional but recommended,
and adding it to the cloud XML regtests is not recommended.

-   The configuration of the LA contents is in
    \$RESOURCES/\$lang/NCS5.1/la.internal.config.stark for both cloud
    and embedded.

    -   By default, as of
        [ONENLU-346302](https://cerence.atlassian.net/browse/ONENLU-346302) -
        Getting issue details\... STATUS , both the cloud and embedded
        configurations should include at least all HP\_\* files in both
        common-app/CTagger/data/jiras_train and
        common-app/CTagger/data/cloud_regtest_jiras/jiras_train, so all
        HPs should be systematically included in embedded and cloud LA
        without requiring any configuration changes.

> **Cloud**
>
> The configuration file for cloud XML regtests is
> \$RESOURCES/\$lang/NCS5.1/regtest.config.stark. It is divided in
> several testsuites; the one where we want to include OneSemantics
> happy paths is called CloudRefHappyPaths.
>
> After completing
> [ONENLU-346302](https://cerence.atlassian.net/browse/ONENLU-346302) -
> Getting issue details\... STATUS , this suite should be considered to
> include all HP\_\* files in
> common-app/CTagger/data/cloud_regtest_jiras/jiras_train, but *not*
> those from common-app/CTagger/data/jiras_train. This is on purpose, so
> that we can choose exactly which HPs to include or not in XML regtests
> just by picking the jiras_train folder inside or outside of the
> cloud_regtest_jiras directory, instead of having long lists of jiras
> to include or exclude in the regtest.config.stark configuration.
>
> Language teams could also opt to systematically include all embedded
> HPs in XML regtest as well, but this would mean that you will have
> significantly more regtests to maintain over time, with the whole
> process of verifying/regenerating every time the correct expected
> annotation changes. This is why it is rather recommended to only
> generate regtests for cloud-focused tasks, with selective additions
> e.g. for CF coverage, in order to minimize your maintenance overhead
> over time.
>
> The most crucial point is that **the HP of Cloud tasks should always
> be added to internal LA and it should always have a regtest,** so the
> HP of cloud tasks must always be added to the cloud_regtest_jiras
> subdirectory. 

## Gazetteers

When new gazetteers are needed for the task, this section may give some
recommendations about e.g. what they should cover, or how they should be
assembled or manipulated in gazetteer.stark.

## Canonicalization

For tasks that involve changes to canonicalization resources, this
section will contain the details of new canonicals to cover (or to
rename or delete) along with examples of corresponding surface forms.

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}When implementing canonicals, it is
always a good idea to check the system specs (which get copied to
\$RESOURCES/common-lang/NCS5.1/system_spec.json), because this spec can
include additional descriptions and examples for canonicals that are not
available in the cano specs.

**Embedded**

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}For a long time, discontinuous mentions
have remained unsupported in Embedded, which affected canonicalization
(parts of a single slot separated by another slot or some untagged
tokens that should have ideally been canonicalized as a whole expression
could only be canonicalized separately). This is not the case anymore,
discontinuous slots are now supported in Embedded as in Cloud.

### CF coverage testing

Cloud woodpecker tests include CF coverage testing: it verifies that
each required canonical in each slot type, appears in at least one XML
regtest.

For each canonicalized slot type, you should have a source FAS file in
\$RESOURCES/\$lang/NCS5.1/CTagger/data/jiras_testonly called
\"cf_testing\_\<slot_type_name\>.fieldannotatedstring, e.g.
cf_testing_DURATION.fieldannotatedstring.

When an implementation task requires to support new canonicals, add one
new test case for each canonical in the relevant file. You can re-use
some of the happy paths examples.

When you run regtest_add_new in the regtest section of instructions
after building full models, these new testcases will be added to the
corresponding XML regtest files, and if your canonicalization resources
were correctly implemented the regtests will contain the expected
canonicals and the CF coverage tests will pass for these canonicals.

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}CF coverage testing actually doesn\'t
only check the cf_testing\_\* XML files for occurrences of canonicals to
cover, but **also XML files for happy paths**; so if a canonical appears
in a HP, it is not strictly required to also have a use case in the
corresponding cf_testing file. These files can be used only to cover the
\"gaps\" of canonicals that aren\'t represented in any regular HP. It is
at the discretion of each language to either keep the cf_testing files
as small as possible and only cover canonicals not already passing
coverage through HPs, or to exhaustively cover all canonicals in their
slot type\'s cf_testing file, depending on what seems more convenient
for their maintenance.

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Because CF coverage tests are based on
XML regtests, it is normal that new canonicals will show as missing in
the coverage of your first new build, even if you have implemented them
in your resources and written the cf_testing or HP FAS files that cover
them. Coverage failures will only disappear once the corresponding XML
regtests have been generated, which can only be done once this new build
is completed.

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Since cloud now requires CF coverage
thresholds to be met not only for canonicals that are set as required
for cloud, but for all supported canonicals, including those introduced
for embedded tasks, **please take CF coverage testing into account also
when working on embedded tasks.** When you implement a task that
introduces a new canonical to the specs (or where a canonical was
already supported in specs but you are newly adding its support to your
resources), please add a corresponding use case to the cloud regtests.
This can for instance be done by adding the task\'s HP to the cloud LA
and XML regtests configuration, or by adding a corresponding line to the
relevant cf_testing\_\... source FAS for XML regtests. (The latter may
be necessary if the HP does not cover all relevant new canonicals).

## ASR Datapatch generation and vocab update

If this section is included in the implementation task, it means that an
ASR update has been requested for the new feature.

Please follow the detailed instructions for the NLU developer in the
page [ASR - NLU
workflow](https://cerence.atlassian.net/wiki/spaces/G5294/pages/2877653009/ASR+-+NLU+workflow).

The instructions in the implementation task should include a link to the
ASRDP ticket that contains more details about the vocab updates that
need to be documented in your NLU language subtask.

The datapatch updates are not expected to require any task-specific
instructions.

## Language specific regex update

If a task requires regexes to be written to handle language-specific
conversions from anno specs to system specs, they will be detailed in
this section.

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Now that embedded and cloud specs are
aligned, **only** use common-app regex rules files in
\$RESOURCES/\$lang/common-app/CTagger/data/correctedannostrings. **Never
write regex files in
\$RESOURCES/\$lang/[NCS5.1]{.underline}/CTagger/data/correctedannostrings**,
this would result in misalignment between your cloud and embedded
models.

The file regex_filter_rules contains rules that will be applied to
conversions from mobileApp (old legacy) anno specs, and
regex_filter_rules.globalConversions contains rules that will be applied
to conversions from globalConversions (merged) anno specs (except for
English, which uses regex_filter_rules for merged anno specs and
regex_filter_rules.mobileApp for old legacy anno specs).

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}For regexes that rely on gazetteer
matching (with a \"tag_value_match_gaz_lists\" field), the value of that
field needs to be adapted according to the actual precise name of
gazetteers in your resources and in your gazetteer.stark configuration.
Gazetteers in regex rules can be accessed with the same naming
conventions as in gazetteer.stark and in jsgf.stark, for instance:

-   If your git repository contains a gazetteer named \"area.gaz\", then
    you can reference it with the name \"git.area\";

-   Any gazetteer declared in gazetteer.stark can be referenced with the
    exact same name, for instance if your gazetteer.stark contains 

-   \'physical_media_source\' {

-   phrases = (

-   gazetteers.\'git.connection_type\'

-   \+ gazetteers.\'git.physical_media_source_without_connection_type\'

-   )

-   }

-   

> then you can use the gazetteer name \"physical_media_source\" as value
> for the field \"tag_value_match_gaz_lists\".

## Data cleaning

Some tasks will require to clean up existing annotated data written in
app specs, typically when a mention or parsetype is renamed, split or
deleted, or when a new mention covers expressions that were previously
not tagged. When that happens, the task instructions should detail what
kind of data to look for and what changes to make.

App specs data can consist of the following:

-   Happy Paths and QA jiras

    -   .fieldannotatedstring files in the jiras_train or jiras_testonly
        folders in \$RESOURCES/\$lang/{common-app,NCS5.1}/CTagger/data

    -   folders \"jiras_external_la\" and \"jiras_train2ndstage\" were
        also common at some point in vlingo to NCSref eras but are now
        obsolete and not expected to be present anymore in OneNLU
        resources.

-   special sets written in app specs (including embedded guarded
    utterances)

    -   **.final**.fieldannotatedstring files in the special-sets or
        special-sets-testonly folders in
        \$RESOURCES/\$lang/{common-app,NCS5.1}/CTagger/data

-   app specs corrections

    -   files with name starting in \"corrected.annostring.new\" in
        \$RESOURCES/\$lang/{common-app,NCS5.1}/CTagger/data/correctedannostrings

Anno specs data should generally not need to be modified manually, they
should be covered by regex conversions (see above).

**Embedded**

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Augmented data are an app spec special
set but it is recommended to exclude them from data cleaning when it
requires some manual changes or careful review, since they are
regenerated regularly: any cleanup effort will be lost after each
regeneration. This should not cause any pipeline failure even for
breaking changes, this set should not be part of data sets for which
validation is strictly enforced (hopefully they should not be included
as a source for the literal annotator).

When data cleanup can be done with a very simple and systematic sed
command that doesn\'t require any manual modifications afterwards, and
this command gets applied to the augmented data set anyway, then you can
keep and commit these changes since it doesn\'t take more effort than
reverting them.

### Setting up the \$FASFILES variable

Whenever it is possible to apply data cleaning in a very systematic way
(e.g. a slot gets remapped in an intent), instructions will provide a
command to do so. This will generally take the form of a sed (or
sometimes perl) command expecting as argument the list of all app specs
data files as an environment variable \$FASFILES.

This variable should be fine-tuned depending on the locations that
contain app specs files in your language setup, and could be different
for your cloud and embedded setups.

Is it advised to start with the following definition based on the list
above that should cover all most common locations of app specs files:

  ----------------------------------------------------------------------------------------------------
  export FASFILES=\"\$RESOURCES/\$lang/common-app/CTagger/data/jiras\*/\*.fieldannotatedstring
  **\$RESOURCES/\$lang/common-app/CTagger/data/cloud_regtest_jiras/jiras\*/\*.fieldannotatedstring**
  \$RESOURCES/\$lang/NCS5.1/CTagger/data/jiras\*/\*.fieldannotatedstring
  \$RESOURCES/\$lang/NCS5.1/CTagger/data/special-sets\*/\*.fieldannotatedstring
  \$RESOURCES/\$lang/common-app/CTagger/data/special-sets\*/\*.fieldannotatedstring
  \$RESOURCES/\$lang/NCS5.1/CTagger/data/correctedannostrings/corrected.annostring.new\*
  \$RESOURCES/\$lang/common-app/CTagger/data/correctedannostrings/corrected.annostring.new\*
  \$RESOURCES/\$lang/NCS5.1/data/literal-annotator/internal/\*string\"
  ----------------------------------------------------------------------------------------------------

  ----------------------------------------------------------------------------------------------------

Adapt to your own setup by removing any of these patterns for which you
have no corresponding file (else you will see error messages for each
unmatched pattern everytime you run a command using the variable); the
command \"ls \$FASFILE\" should show you a list of all relevant files
without errors (use the command \"ls \$FASFILES \> /dev/null\" to see
only error messages).

In particular, the cloud_regtest_jiras locations will only exist after
completing
[ONENLU-346302](https://cerence.atlassian.net/browse/ONENLU-346302) -
Getting issue details\... STATUS , and NCS5.1/\.../jiras\* may not exist
anymore if the cleanup in that task could be completed entirely without
hindrance.

The appropriate setup for the FASFILES variable may not be the same for
your cloud and embedded setups (for instance, at the time of writing,
you are expected to have some jiras in the NCS5.1 subdirectory in your
cloud resources, but likely not in your embedded resources. To avoid
having to re-set your appropriate FASFILES for every task, you can
declare two different variables FASFILES_EMBEDDED and FASFILES_CLOUD in
your private bashrc, and substitute \$FASFILES for one of them whenever
you encounter it in example commands in task instructions.

## Unit tests, JSGFs & coverage tests

This section is for the development of JSGF and unit test resources. The
task instructions may contain notes that are specific to the task, for
instance considerations about particular carrier phrases that should be
included, reminders about anno and app specs correspondence, etc.

For detailed instructions and example commands check the [How-to
(unicorn): unit-tests, jsgf,
coverage](https://cerence.atlassian.net/wiki/spaces/C3247/pages/1511424592/How-to+unicorn+unit-tests+jsgf+coverage).

Make sure to cover all required steps:

-   Create or update unit tests for the intents in scope and validate
    them (mandatory for cloud, optional for embedded)

-   Create or update JSGFs for the intents in scope and test the
    coverage (mandatory, but only possible if unit tests were created)

-   Regenerate coverage tests (optional, but very useful to verify that
    all new semantic signatures are well covered *before* training full
    models and checking the coverage results in woodpecker tests).

**Embedded**

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Due to limited bandwidth, for embedded
tasks, development can be limited to JSGFs skipping the unit test work
(but unit tests can be also developed if you have the bandwidth).
Coverage test generation has been adapted to include JSGF generation and
allow coverage testing without unit tests.

## Backward compatibility mapping

When major changes happen, backward mapping rules are needed to recover
the former tagging for clients still using an older version of the
specs. Most of the time, for the simplest cases, this is done with
language-independent rules, and in such cases no action from language
development is needed. In some cases, the mapping rules need to rely on
language-specific aspects, e.g. if a mapping needs to happen when
particular phrases are part of the carrier phrase or of a slot, or when
a slot has been removed and its contents is now supported untagged in
the carrier phrase. In such cases, this section will be included in
tasks and request language devs to provide particular phraselists or
regexes that will be combined with language-independent rule structures
to generate language-specific backward mapping rules.

## Staging and training configuration

Some changes to the configuration of various staging and training
configuration files are needed when new features are implemented.

### Add new JSGF/unit test intents in stage.stark

When adding a new JSGF to support a new intent, it must be listed in
stage.stark to be used in data staging.

The standard files with a list of grammars to use should now be located
in anno-lang (\$RESOURCES/\$lang/common-app) for all languages and
imported by each project\'s stage.stark in the respective cloud and
embedded branches of main resources:

-   in jsgf_Global.stark for resources in merged (global) anno specs,
    for all languages;

-   in jsgf_mobileApp_parsetype.stark for resources in legacy mobilApp
    anno specs, for older languages that still have resources in these
    specs.

### Add new gazetteers to model training

In general, when an implementation task requires to create a new
gazetteer, it should be helpful for model training to add it as a
dictionary (unless indicated otherwise in the task instructions).

To do so for the main seq2seq models, declare this gazetteer in both
dictionaries.stark and seq2seq.config.json.

### Extraction specs

If a new parsetype with mentions is added, or a new mention is added in
an existing parsetype, you may want to check if extraction specs need to
be setup (see [Staging the data (finalize) Extraction spec (NOTE appspec
level)](https://cerence.atlassian.nethttps://cerence.atlassian.net/wiki/pages/viewpage.action?pageId=1514966046)
for documentation about extraction specs).

The location of the extraction specs file can be found in
\$RESOURCES/\$lang/NCS5.1/CTagger/config/stage/stageconfig.json (under
the \"extraction-spec\" key).

![(warning)](media/image1.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}If your extraction specs are currently
located somewhere in \$RESOURCES/\$lang/NCS5.1, and therefore not shared
between cloud and embedded, it is strongly recommended to merge them
into a single file located in \$RESOURCES/\$lang/common-app (anno-lang),
and modify your stageconfig.json configs to use that shared extraction
specs file.

If you\'re unsure about which rules to set, it is generally a good idea
to check the specs already existing for similar parsetypes (e.g. from
the same domain) and for the same or similar mentions in other
parsetypes, and reuse the same rules.

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}If you think it would be useful to set a
default extraction specs per slot types, and have them used by default
by all slots of that type in all intents, consider upvoting or
commenting on
[SIBD-3451](https://cerence.atlassian.net/browse/SIBD-3451) - Getting
issue details\... STATUS .

**Cloud**

## Run staging and training pipeline

For cloud tasks, it is necessary to run a full blackbird pipeline
locally (in order to regenerate regtests, and to obtain evaluation
results).

Run the command gradlewp build.

## Generate new regtests

Once new models are built, you can generate new regtests with the
command regtest_add_new. This will create new XML regtest files for new
FAS file sources (notably the new HP FAS for this task), and also add
new test cases for any existing FAS source for which you added new use
cases (e.g. any existing CF testing FAS file where you added a new test
case for a new cform). If no new XML regtest is created for the new
happy path file, check your regtest configuration (refer to the happy
path section of the instructions above).

It can be useful to have a quick look at the newly generated regtests to
confirm that everything looks as expected (no cform missing, no
unextracted surface form, no lemmatization missing).

Once new regtests are generated, run regtests one more time (gradlewp
regtests) to confirm that they are all passing correctly (they might
fail if the regtests were missing from the LA config for instance).

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}It should be more efficient to combine
this with the regtest part of the minimal testing requirements, since
both require to (re-)generate regtests and then to execute all regtests
again.

## Troubleshooting

This section may be added to give tips to troubleshoot issues that can
be encountered during this task.

## Test Plan

If needed, the second test plan section in the instructions will contain
more details about the test plan that is specific for that task. This
will typically include some details about a likely kind of regression to
watch for in already supported signatures, or precise instructions in
the case of additional or scrutiny testing.

The test plan should always be categorized as one of \"minimal
testing\", \"normal testing\", \"additional testing\" or \"scrutiny
testing\".

They generally rely in good part on standard woodpecker tests.

**Cloud**

cloudref has a large set of woodpecker tests, the most important for
standard implementation tasks are:

-   Coverage tests:

    -   \"CovTest: Coverage OneSemantics Required\": checks if each
        signature configured as required for your language appears in
        your coverage tests.

    -   \"CovTest: Happy-Paths Coverage Required\": checks if each
        signature configured as required for your language appears *in a
        happy path regtest*.

    -   \"RegTest: CF Coverage Required\": checks if each canonical
        configured as required for your language appears in a regtest
        (CF coverage regtest, or optionally happy path regtest).

-   Quality tests:

    -   \"CovTest: SemSigs above (1%/50%/80%)-modelsOnly Required\":
        three sets of tests that check if each signature configured as
        required for your language meets a given accuracy threshold,
        averaged on all examples of that signature in your coverage
        tests, *with statistical models only* (Gala is disabled).

    -   \"CovTest: SemSigs above 90% Required\": checks if each
        signature configured as required for your language meets the
        accuracy threshold of 90% averaged on all examples of that
        signature in your coverage tests, on the full NLU pipeline
        including Gala.

-   Regtests:

    -   various tests whose name start with \"Regtest:\", which monitor
        regressions on XML regtests. They should generally all remain at
        100%, except \"NCS Ref Imported QA Suite\" which is relaxed to
        99%.

The overall quality goal for CloudRef is to always keep these metrics at
100%; ideally, the only exceptions would be for semantic signatures and
canonicals that were recently added for new implementation tasks still
pending or in progress.

For each of these tests a counterpart without \"Required\" in its name
also exists, which considers all the signatures and canonicals that are
\*allowed\* for your language, not only those that are \*required\*.
These variants should be less useful in the context of implementation
tasks for cloud, since they will report a lot of coverage or accuracy
failures that can actually be ignored.

**Embedded**

Out of the above set, Embedded woodpecker tests only includes coverage
tests on semantic signatures (currently under the obsolete name of
\"CovTest: Coverage Audi HCP3\").

Since embedded project specs don\'t have a detailed tracking of the
expected actual support for each language, this test corresponds to the
cloud variant without \"Required\"; it considers all the signatures and
canonicals that are allowed for the language, and therefore it is not
expected to reach anywhere near 100%.

### Minimal testing

This is a reduced testing requirement for tasks that do not introduce
any new semantic signature or canonical, and generally consists in
ensuring that the changes done during the task do not break anything -
inspect test results after implementation, and verify that no unexpected
degradation occurs.

**Cloud**

For cloud, this particularly means ensuring that the most important
metrics listed above still meet their expected threshold (generally
100%), or at least that no new degradation appears after the task is
completed compared to previous reference results.

This includes regenerating regtests if the implementation of the task
causes changes in the result of some use cases (after verifying that
these changes are expected and correct):

-   Examine the detailed reason for the regtest failure in the
    regression test report, e.g.
    \$NLTOOLS_WORK/\$lang/NCS5.1/test/latest/\${lang/-/}/BlackbirdQualityTestSuite/RegTest\_\_CloudRef_Annotator_HappyPaths_Suite/CloudRefHappyPaths.RegressionTestReport

    -   If the expected result is still correct, but the model
        prediction (hyp) is wrong, then don\'t regenerate the regtest,
        the cause of the regression needs to be fixed in the models
        instead.

    -   If the expected result is not correct anymore, and the models
        are returning a correct result, then the regtest needs to be
        regenerated.

-   Assemble a list of all the names of the regtests that need to be
    regenerated, then delete them with regtest_remove \<JIRA1\>
    \<JIRA2\> \....

-   Regenerate all deleted regtests with regtest_add_new

-   Inspect the changes in the regenerated regtests with git diff to
    ensure that only the regtests that have been assessed as obsolete
    are modified and that no other unrelated changes occur.

-   Run regtests once more (gradlewp regtests) to confirm that all
    regression tests are now passing 100% again.

Task instructions may mention some particular regression risks to look
for (e.g. adding some new surface forms for a slot type could affect
accuracy of semantic signatures with slots of that type).

### Normal testing

This is the most common test plan for regular implementation tasks that
involves adding support for new semantic signatures and/or new
canonicals. On top of the minimal testing requirements, do the
following:

**Cloud**

For cloud, we must make sure that the new semantic signatures are
covered in coverage tests and HP coverage tests, and that they reach the
required accuracy thresholds (80% models only, 90% with Gala included),
and that new canonicals are covered in the CF coverage test. In general
this will mean bringing these metrics back to 100%, except if other new
semsigs or canonicals are introduced at the same time for other tasks.

There are different semsigs accuracy tests with different thresholds
because some years ago, when the FC and CF of a milestone where one
month apart, it was sufficient to reach 50% with models only during the
FC sprint, and pushing to 80% could be deferred to the CF sprint.
Nowadays FC and CF are only one release apart, and tasks are opened too
late for FC inclusion most of the time, so the distinction has less use,
except for a rough indication of how seriously the accuracy target is
missed.

The detailed list of failing semantic signatures can be found in the
report of its testsuite in
\$NLTOOLS_WORK/\$lang/NCS5.1/test/latest/reports/json:

-   \${lang/-/}.BlackbirdCoverageTestSuite.txt for all coverage tests
    (coverage-of-coverage, HP coverage and cform coverage);

-   \${lang/-/}.BlackbirdQualityTestSuite.txt for semsig accuracy and
    regtests.

Search for the exact name of the test in the file, then for the next
occurrence of \"not-matched\".

![(info)](media/image2.tmp){width="0.16666666666666666in"
height="0.16666666666666666in"}Since the happy path coverage tests and
the CF coverage tests both rely on regtests, they will still show
failures for new features the first time you run a full model build
after implementing them. Once your new models are ready, you can
generate new regtests with regtest_add_new and re-run regtests and
coverage tests; then they should show as passing.

**Embedded**

For embedded, normal testing only consists in checking the presence of
relevant signatures in the coverage tests. The embedded workflow
doesn\'t require to fully retrain models for every implementation task,
which means that the accuracy of models on new signatures can\'t be
checked at that time. For implementation testing, please only run data
staging and then rely on signatures_found.json and
signatures_missing.json to check that all required new signatures are
correctly covered (see documentation linked in the \"Unit tests, JSGFs &
coverage tests\" section above for details).

Once new embedded models are released, you can then check the accuracy
results per semantic signature for the recently developed signatures and
work on improvements if needed.

### Additional/scrutiny testing

This means that the task requires a particular testing strategy, either
instead of or in addition to normal testing. Details will be explained
in the task instructions.

## Logging working hours in JIRA

Please always log the actual amount of hours spent to complete the task
in your language subtask.

-   Click on the drop-down button More and select Log work to introduce
    the amount of hours.

# Instructions for tech primes

Refer to the [One NLU technical design
reference](https://cerence.atlassian.net/wiki/spaces/G5294/pages/1525534170/One+NLU+technical+design+reference),
in particular the section [ONENLU implementation ticket:instructions for
lang
devs](https://cerence.atlassian.net/wiki/spaces/G5294/pages/1525534170/One+NLU+technical+design+reference#OneNLUtechnicaldesignreference-ONENLUimplementationticket:instructionsforlangdevs)
