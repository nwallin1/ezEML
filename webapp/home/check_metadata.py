#!/usr/bin/env python
# -*- coding: utf-8 -*-

""":Mod: evaluate.py

:Synopsis:

:Author:
    ide

:Created:
    6/20/20
"""

import collections
from enum import Enum

from flask import (
    Blueprint, Flask, url_for, render_template, session, app
)

from metapype.eml import names
import metapype.eml.validate as validate
from metapype.eml.validation_errors import ValidationError
import metapype.eml.evaluate as evaluate
from metapype.eml.evaluation_warnings import EvaluationWarning
from metapype.model.node import Node
from webapp.home.metapype_client import load_eml, VariableType
from webapp.pages import *


app = Flask(__name__)
home = Blueprint('home', __name__, template_folder='templates')


class EvalSeverity(Enum):
    ERROR = 1
    WARNING = 2
    INFO = 3


class EvalType(Enum):
    REQUIRED = 1
    RECOMMENDED = 2
    BEST_PRACTICE = 3


def get_eval_entry(id, link=None, section=None, item=None):
    try:
        vals = session[f'__eval__{id}']
        if section:
            vals[0] = section
        if item:
            vals[1] = item
        return Eval_Entry(section=vals[0], item=vals[1], severity=EvalSeverity[vals[2]], type=EvalType[vals[3]],
                          explanation=vals[4], link=link)
    except:
        return None


def add_to_evaluation(id, link=None, section=None, item=None):
    entry = get_eval_entry(id, link, section, item)
    if entry:
        evaluation.append(entry)


Eval_Entry = collections.namedtuple(
    'Evaluate_Entry', ["section", "item", "severity", "type", "explanation", "link"])
evaluation = []


def find_min_unmet(errs, node_name, child_name):
    for err_code, msg, node, *args in errs:
        if err_code == ValidationError.MIN_OCCURRENCE_UNMET:
            children, min = args
            if node.name == node_name and child_name in children:
                return True
    return False


def find_min_unmet_for_list(errs, node_name, child_names):
    for err_code, msg, node, *args in errs:
        if err_code == ValidationError.MIN_OCCURRENCE_UNMET and node.name == node_name:
            children, min = args
            if set(child_names) == set(children):
                return True
    return False


def find_content_empty(errs, node_name):
    found = []
    for err in errs:
        err_code, _, node, *_ = err
        if err_code == ValidationError.CONTENT_EXPECTED_NONEMPTY and node.name == node_name:
            found.append(err)
    return found


def find_err_code(errs, err_code_to_find, node_name):
    found = []
    for err in errs:
        err_code, _, node, *_ = err
        if err_code == err_code_to_find and node.name == node_name:
            found.append(err)
    return found


def check_dataset_title(eml_node, packageid):
    link = url_for(PAGE_TITLE, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    validation_errs = validate_via_metapype(dataset_node)
    # Is title node missing?
    if find_min_unmet(validation_errs, names.DATASET, names.TITLE):
        add_to_evaluation('title_01', link)
        return
    # Is title node content empty?
    title_node = eml_node.find_single_node_by_path([names.DATASET, names.TITLE])
    validation_errs = validate_via_metapype(title_node)
    if find_content_empty(validation_errs, names.TITLE):
        add_to_evaluation('title_01', link)
        return

    evaluation_warnings = evaluate_via_metapype(title_node)
    # Is the title too short?
    if find_err_code(evaluation_warnings, EvaluationWarning.TITLE_TOO_SHORT, names.TITLE):
        add_to_evaluation('title_02', link)


def check_responsible_party(rp_node:Node, section:str=None, item:str=None,
                            page:str=None, packageid:str=None, node_id:str=None):
    link = url_for(page, packageid=packageid, node_id=node_id)
    validation_errs = validate_via_metapype(rp_node)

    # Last name is required if other parts of name are given
    if find_min_unmet(validation_errs, names.INDIVIDUALNAME, names.SURNAME):
        add_to_evaluation('responsible_party_04', link, section, item)

    # At least one of surname, organization name, or position name is required
    if find_min_unmet_for_list(validation_errs, rp_node.name, [names.INDIVIDUALNAME, names.ORGANIZATIONNAME, names.POSITIONNAME]):
        add_to_evaluation('responsible_party_01', link, section, item)

    # Role, if required
    if find_min_unmet(validation_errs, rp_node.name, names.ROLE):
        add_to_evaluation('responsible_party_03', link, section, item)

    evaluation_warnings = evaluate_via_metapype(rp_node)
    # User ID is recommended
    if find_err_code(evaluation_warnings, EvaluationWarning.ORCID_ID_MISSING, rp_node.name):
        add_to_evaluation('responsible_party_02', link, section, item)


def check_creators(eml_node, packageid):
    link = url_for(PAGE_CREATOR_SELECT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    validation_errs = validate_via_metapype(dataset_node)

    if find_min_unmet(validation_errs, names.DATASET, names.CREATOR):
        add_to_evaluation('creators_01', link)
    else:
        creator_nodes = eml_node.find_all_nodes_by_path([names.DATASET, names.CREATOR])
        for creator_node in creator_nodes:
            check_responsible_party(creator_node, 'Creators', 'Creator', PAGE_CREATOR, packageid, creator_node.id)


def check_metadata_providers(eml_node, packageid):
    link = url_for(PAGE_METADATA_PROVIDER_SELECT, packageid=packageid)
    metadata_provider_nodes = eml_node.find_all_nodes_by_path([names.DATASET, names.METADATAPROVIDER])
    if metadata_provider_nodes and len(metadata_provider_nodes) > 0:
        for metadata_provider_node in metadata_provider_nodes:
            check_responsible_party(metadata_provider_node, 'Metadata Providers', 'Metadata Provider',
                                    PAGE_METADATA_PROVIDER, packageid, metadata_provider_node.id)


def check_associated_parties(eml_node, packageid):
    link = url_for(PAGE_ASSOCIATED_PARTY_SELECT, packageid=packageid)
    associated_party_nodes = eml_node.find_all_nodes_by_path([names.DATASET, names.ASSOCIATEDPARTY])
    if associated_party_nodes and len(associated_party_nodes) > 0:
        for associated_party_node in associated_party_nodes:
            check_responsible_party(associated_party_node, 'Associated Parties', 'Associated Party',
                                    PAGE_ASSOCIATED_PARTY, packageid, associated_party_node.id)


def check_dataset_abstract(eml_node, packageid):
    link = url_for(PAGE_ABSTRACT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    evaluation_warnings = evaluate_via_metapype(dataset_node)

    if find_err_code(evaluation_warnings, EvaluationWarning.DATASET_ABSTRACT_MISSING, names.DATASET):
        add_to_evaluation('abstract_01', link)
        return

    if find_err_code(evaluation_warnings, EvaluationWarning.DATASET_ABSTRACT_TOO_SHORT, names.DATASET):
        add_to_evaluation('abstract_02', link)
        return


def check_keywords(eml_node, packageid):
    link = url_for(PAGE_KEYWORD_SELECT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    evaluation_warnings = evaluate_via_metapype(dataset_node)

    if find_err_code(evaluation_warnings, EvaluationWarning.KEYWORDS_MISSING, names.DATASET):
        add_to_evaluation('keywords_01', link)
        return

    if find_err_code(evaluation_warnings, EvaluationWarning.KEYWORDS_INSUFFICIENT, names.DATASET):
        add_to_evaluation('keywords_02', link)
        return


def check_intellectual_rights(eml_node, packageid):
    link = url_for(PAGE_INTELLECTUAL_RIGHTS, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    evaluation_warnings = evaluate_via_metapype(dataset_node)

    if find_err_code(evaluation_warnings, EvaluationWarning.INTELLECTUAL_RIGHTS_MISSING, names.DATASET):
        add_to_evaluation('intellectual_rights_01', link)
        return


def check_coverage(eml_node, packageid):
    link = url_for(PAGE_GEOGRAPHIC_COVERAGE_SELECT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    evaluation_warnings = evaluate_via_metapype(dataset_node)

    if find_err_code(evaluation_warnings, EvaluationWarning.DATASET_COVERAGE_MISSING, names.DATASET):
        add_to_evaluation('coverage_01', link)
        return


def check_geographic_coverage(eml_node, packageid):
    link = url_for(PAGE_GEOGRAPHIC_COVERAGE_SELECT, packageid=packageid)
    geographic_coverage_nodes = eml_node.find_all_nodes_by_path([names.DATASET, names.COVERAGE, names.GEOGRAPHICCOVERAGE])
    for geographic_coverage_node in geographic_coverage_nodes:
        link = url_for(PAGE_GEOGRAPHIC_COVERAGE, packageid=packageid, node_id=geographic_coverage_node.id)
        validation_errs = validate_via_metapype(geographic_coverage_node)
        if find_content_empty(validation_errs, names.GEOGRAPHICDESCRIPTION):
            add_to_evaluation('geographic_coverage_01', link)
        if find_err_code(validation_errs, ValidationError.CONTENT_EXPECTED_RANGE, names.WESTBOUNDINGCOORDINATE):
            add_to_evaluation('geographic_coverage_03', link)
        if find_err_code(validation_errs, ValidationError.CONTENT_EXPECTED_RANGE, names.EASTBOUNDINGCOORDINATE):
            add_to_evaluation('geographic_coverage_04', link)
        if find_err_code(validation_errs, ValidationError.CONTENT_EXPECTED_RANGE, names.NORTHBOUNDINGCOORDINATE):
            add_to_evaluation('geographic_coverage_05', link)
        if find_err_code(validation_errs, ValidationError.CONTENT_EXPECTED_RANGE, names.SOUTHBOUNDINGCOORDINATE):
            add_to_evaluation('geographic_coverage_06', link)


def get_attribute_type(attrib_node:Node):
    mscale_node = attrib_node.find_child(names.MEASUREMENTSCALE)
    nominal_node = mscale_node.find_child(names.NOMINAL)
    if nominal_node:
        enumerated_domain_node = nominal_node.find_single_node_by_path([names.NONNUMERICDOMAIN, names.ENUMERATEDDOMAIN])
        if enumerated_domain_node:
            return VariableType.CATEGORICAL
        text_domain_node = nominal_node.find_single_node_by_path([names.NONNUMERICDOMAIN, names.TEXTDOMAIN])
        if text_domain_node:
            return VariableType.TEXT
    ratio_node = mscale_node.find_child(names.RATIO)
    if ratio_node:
        return VariableType.NUMERICAL
    datetime_node = mscale_node.find_child(names.DATETIME)
    if datetime_node:
        return VariableType.DATETIME
    return None


def check_attribute(eml_node, packageid, data_table_node:Node, attrib_node:Node):
    attr_type = get_attribute_type(attrib_node)
    mscale = None
    if attr_type == VariableType.CATEGORICAL:
        page = PAGE_ATTRIBUTE_CATEGORICAL
        mscale = VariableType.CATEGORICAL.name
    elif attr_type == VariableType.NUMERICAL:
        page = PAGE_ATTRIBUTE_NUMERICAL
        mscale = VariableType.NUMERICAL.name
    elif attr_type == VariableType.TEXT:
        page = PAGE_ATTRIBUTE_TEXT
        mscale = VariableType.TEXT.name
    elif attr_type == VariableType.DATETIME:
        page = PAGE_ATTRIBUTE_DATETIME
        mscale = VariableType.DATETIME.name
    link = url_for(page, packageid=packageid, dt_node_id=data_table_node.id, node_id=attrib_node.id, mscale=mscale)

    validation_errs = validate_via_metapype(attrib_node)
    if find_content_empty(validation_errs, names.ATTRIBUTEDEFINITION):
        add_to_evaluation('attributes_01', link)

    # Categorical
    if find_min_unmet(validation_errs, names.ENUMERATEDDOMAIN, names.CODEDEFINITION):
        add_to_evaluation('attributes_04', link)
    if find_content_empty(validation_errs, names.CODE):
        add_to_evaluation('attributes_05', link)
    if find_content_empty(validation_errs, names.DEFINITION):
        add_to_evaluation('attributes_06', link)

    # Numerical
    if find_min_unmet_for_list(validation_errs, names.UNIT, [names.STANDARDUNIT, names.CUSTOMUNIT]):
        add_to_evaluation('attributes_02', link)

    # DateTime
    if find_content_empty(validation_errs, names.FORMATSTRING):
        add_to_evaluation('attributes_03', link)


def check_data_table(eml_node, packageid, data_table_node:Node):
    link = url_for(PAGE_DATA_TABLE, packageid=packageid, node_id=data_table_node.id)
    validation_errs = validate_via_metapype(data_table_node)

    if find_min_unmet(validation_errs, names.DATATABLE, names.ENTITYNAME):
        add_to_evaluation('data_table_01', link)
    if find_min_unmet(validation_errs, names.DATATABLE, names.ENTITYDESCRIPTION):
        add_to_evaluation('data_table_02', link)
    if find_min_unmet(validation_errs, names.PHYSICAL, names.OBJECTNAME):
        add_to_evaluation('data_table_03', link)
    if find_min_unmet(validation_errs, names.DATATABLE, names.ATTRIBUTELIST):
        add_to_evaluation('data_table_04', link)

    evaluation_warnings = evaluate_via_metapype(data_table_node)
    if find_err_code(evaluation_warnings, EvaluationWarning.DATATABLE_DESCRIPTION_MISSING, names.DATATABLE):
        add_to_evaluation('data_table_02', link)

    attribute_list_node = data_table_node.find_child(names.ATTRIBUTELIST)
    if attribute_list_node:
        attribute_nodes = attribute_list_node.find_all_children(names.ATTRIBUTE)
        for attribute_node in attribute_nodes:
            check_attribute(eml_node, packageid, data_table_node, attribute_node)


def check_data_tables(eml_node, packageid):
    link = url_for(PAGE_DATA_TABLE_SELECT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    evaluation_warnings = evaluate_via_metapype(dataset_node)
    if find_err_code(evaluation_warnings, EvaluationWarning.DATATABLE_MISSING, names.DATASET):
        add_to_evaluation('data_table_05', link)

    data_table_nodes = eml_node.find_all_nodes_by_path([names.DATASET, names.DATATABLE])
    for data_table_node in data_table_nodes:
        check_data_table(eml_node, packageid, data_table_node)


def check_contacts(eml_node, packageid):
    link = url_for(PAGE_CONTACT_SELECT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    validation_errs = validate_via_metapype(dataset_node)
    if find_min_unmet(validation_errs, names.DATASET, names.CONTACT):
        add_to_evaluation('contacts_01', link=link)
    contact_nodes = eml_node.find_all_nodes_by_path([
        names.DATASET,
        names.CONTACT
    ])
    for contact_node in contact_nodes:
        check_responsible_party(contact_node, 'Contacts', 'Contact', PAGE_CONTACT,
                                packageid, contact_node.id)


def check_method_step(method_step_node):
    validation_errors = validate_via_metapype(method_step_node)
    # FIXME - rule allows empty content for description. What to do about this?


def check_method_steps(eml_node, packageid):
    link = url_for(PAGE_METHOD_STEP_SELECT, packageid=packageid)
    dataset_node = eml_node.find_child(names.DATASET)
    evaluation_warnings = evaluate_via_metapype(dataset_node)
    if find_err_code(evaluation_warnings, EvaluationWarning.DATASET_METHOD_STEPS_MISSING, names.DATASET):
        add_to_evaluation('methods_01', link)

    method_step_nodes = eml_node.find_all_nodes_by_path([
        names.DATASET,
        names.METHODS,
        names.METHODSTEP
    ])
    for method_step_node in method_step_nodes:
        check_method_step(method_step_node)


def check_project_award(award_node, packageid):
    link = url_for(PAGE_FUNDING_AWARD, packageid=packageid, node_id=award_node.id)
    validation_errors = validate_via_metapype(award_node)
    if find_min_unmet(validation_errors, names.AWARD, names.FUNDERNAME) or \
            find_content_empty(validation_errors, names.FUNDERNAME):
        add_to_evaluation('project_04', link)
    if find_min_unmet(validation_errors, names.AWARD, names.TITLE) or \
            find_content_empty(validation_errors, names.TITLE):
        add_to_evaluation('project_05', link)


def check_project(eml_node, packageid):
    link = url_for(PAGE_PROJECT, packageid=packageid)
    project_node = eml_node.find_single_node_by_path([names.DATASET, names.PROJECT])
    if project_node:
        validation_errors = validate_via_metapype(project_node)
        if find_min_unmet(validation_errors, names.PROJECT, names.TITLE) or \
            find_content_empty(validation_errors, names.TITLE):
            add_to_evaluation('project_01', link)
        if find_min_unmet(validation_errors, names.PROJECT, names.PERSONNEL):
            add_to_evaluation('project_02', link)
    else:
        dataset_node = eml_node.find_child(names.DATASET)
        evaluation_warnings = evaluate_via_metapype(dataset_node)
        if find_err_code(evaluation_warnings, EvaluationWarning.DATASET_PROJECT_MISSING, names.DATASET):
            add_to_evaluation('project_03', link)

    project_personnel_nodes = eml_node.find_all_nodes_by_path([
        names.DATASET,
        names.PROJECT,
        names.PERSONNEL
    ])
    for project_personnel_node in project_personnel_nodes:
        check_responsible_party(project_personnel_node, "Project", "Project Personnel",
                                PAGE_PROJECT_PERSONNEL, packageid, project_personnel_node.id)

    project_award_nodes = eml_node.find_all_nodes_by_path([
        names.DATASET,
        names.PROJECT,
        names.AWARD
    ])
    for project_award_node in project_award_nodes:
        check_project_award(project_award_node, packageid)


def check_other_entity(entity_node, packageid):
    link = url_for(PAGE_OTHER_ENTITY, packageid=packageid, node_id=entity_node.id)

    validation_errors = validate_via_metapype(entity_node)
    if find_min_unmet(validation_errors, names.OTHERENTITY, names.ENTITYNAME):
        add_to_evaluation('other_entity_01', link)
    if find_min_unmet(validation_errors, names.OTHERENTITY, names.ENTITYTYPE):
        add_to_evaluation('other_entity_02', link)

    evaluation_warnings = evaluate_via_metapype(entity_node)
    if find_err_code(evaluation_warnings, EvaluationWarning.OTHER_ENTITY_DESCRIPTION_MISSING, names.OTHERENTITY):
        add_to_evaluation('other_entity_03', link)


def check_other_entities(eml_node, packageid):
    other_entity_nodes = eml_node.find_all_nodes_by_path([names.DATASET, names.OTHERENTITY])
    for other_entity_node in other_entity_nodes:
        check_other_entity(other_entity_node, packageid)


def eval_entry_to_string(eval_entry):
    return f'Section:&nbsp;{eval_entry.section}<br>Item:&nbsp;{eval_entry.item}<br>Severity:&nbsp;{eval_entry.severity.name}<br>Type:&nbsp;{eval_entry.type.name}<br>Explanation:&nbsp;{eval_entry.explanation}<br><a href="{eval_entry.link}">Link</a>'


def to_string(evaluation):
    if evaluation and len(evaluation) > 0:
        s = ''
        for eval_entry in evaluation:
            s += eval_entry_to_string(eval_entry) + '<p/>'
        return s
    else:
        return "OK!"


def collect_entries(evaluation, section):
    return [entry for entry in evaluation if entry.section == section]


def format_entry(entry:Eval_Entry):
    output = '<tr>'
    output += f'<td class="eval_table" valign="top"><a href="{entry.link}">{entry.item}</a></td>'
    output += f'<td class="eval_table" valign="top">{entry.severity.name.title()}</td>'
    output += f'<td class="eval_table" valign="top">{entry.type.name.title()}</td>'
    output += f'<td class="eval_table" valign="top">{entry.explanation}</td>'
    output += '</tr>'
    return output


def format_output(evaluation):
    sections = ['Title', 'Creators', 'Metadata Providers', 'Associated Parties', 'Abstract', 'Keywords',
                'Intellectual Rights', 'Coverage', 'Geographic Coverage', 'Temporal Coverage',
                'Taxonomic Coverage', 'Maintenance', 'Contacts', 'Methods', 'Project', 'Data Tables',
                'Other Entities']

    severities = [EvalSeverity.ERROR, EvalSeverity.WARNING, EvalSeverity.INFO]

    all_ok = True
    output = '<span style="font-family: Helvetica,Arial,sans-serif;">'
    for section in sections:
        entries = collect_entries(evaluation, section)
        if not entries:
            continue
        all_ok = False
        output += f'<h3>{section}</h3><table class="eval_table" width=100% style="padding: 10px;"><tr><th class="eval_table" align="left" width=17%>Item</th>' \
                  f'<th class="eval_table" align="left" width=8%>Severity</th><th class="eval_table" align="left" width=14%>Reason</th><th align="left" width=61%>Explanation</th></tr>'
        for severity in severities:
            for entry in entries:
                if entry.severity == severity:
                    output += format_entry(entry)
        output += '</table><br>'
    if all_ok:
        output += '<h4>Everything looks good!</h4>'
    output += '</span>'
    return output


def check_eml(packageid:str):
    # global evaluation, metapype_validation_errs, metapype_evaluation
    global evaluation
    evaluation = []

    eml_node = load_eml(packageid)

    check_dataset_title(eml_node, packageid)
    check_creators(eml_node, packageid)
    check_metadata_providers(eml_node, packageid)
    check_associated_parties(eml_node, packageid)
    check_dataset_abstract(eml_node, packageid)
    check_keywords(eml_node, packageid)
    check_intellectual_rights(eml_node, packageid)
    check_coverage(eml_node, packageid)
    check_geographic_coverage(eml_node, packageid)
    check_contacts(eml_node, packageid)
    check_method_steps(eml_node, packageid)
    check_project(eml_node, packageid)
    check_data_tables(eml_node, packageid)
    check_other_entities(eml_node, packageid)
    return format_output(evaluation)


def validate_via_metapype(node):
    errs = []
    try:
        validate.tree(node, errs)
    except Exception as e:
        print(f'validate_via_metapype: node={node.name} exception={e}')
    return errs


def evaluate_via_metapype(node):
    eval = []
    try:
        evaluate.tree(node, eval)
    except Exception as e:
        print(f'evaluate_via_metapype: node={node.name} exception={e}')
    return eval





