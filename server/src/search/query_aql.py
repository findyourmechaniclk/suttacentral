import re

from search import constant


def extract_query_conditions(param):
    param = re.sub(r'(\w+): ', r'\1:', param)
    result = {}
    author = re.search(f"{constant.CMD_BY}([\w-]+)", param)
    if author:
        result["author"] = author[1].strip()
    collection = re.search(f"{constant.CMD_IN}([\w-]+)", param)
    if collection:
        result["collection"] = collection[1].strip()

    if author or collection:
        extract_rest_keywords(result, param)

    if 'or' in result and len(result['or']) == 1 and result['or'][0] == '':
        del result['or']

    if 'and' in result and len(result['and']) == 1 and result['and'][0] == '':
        del result['and']

    return result


def extract_rest_keywords(result, param):
    """
    Note:
        This assumes only a single author filter is specified.  This function
        will silently clobber any additional author filters.  Ditto for
        collection.  Update extract_query_conditions if/when we want to handle
        multiple authors or collections, or raise an error when #2978 exists.
    """
    rest_param = ''
    param_tokens = param.split()
    for term in param.split():
        if term.startswith(constant.CMD_BY) or term.startswith(constant.CMD_IN):
            param_tokens.remove(term)
    rest_param = ' '.join(param_tokens)

    # if (
    #     not rest_param.startswith("'")
    #     and not rest_param.startswith('"')
    #     and 'OR' not in rest_param
    #     and 'AND' not in rest_param
    #     and 'NOT' not in rest_param
    #     and ' ' in rest_param
    # ):
    #     rest_param = rest_param.replace(' ', ' AND ')

    # if (rest_param.startswith("'") or rest_param.startswith('"')):
    #     rest_param = rest_param[1:-1]

    if 'OR' in rest_param:
        operator = constant.OPERATOR_OR
        _extract_params_by_operator(rest_param, operator, result, "or")
    elif 'AND' in rest_param:
        operator = constant.OPERATOR_AND
        _extract_params_by_operator(rest_param, operator, result, "and")
    elif 'NOT' in rest_param:
        or_param_list = [rest_param.split('NOT')[0].strip()]
        not_param_list = [rest_param.split('NOT')[1].strip()]
        result["or"] = or_param_list
        result["not"] = not_param_list
    else:
        or_param_list = [rest_param.strip()]
        result["or"] = or_param_list


def _extract_params_by_operator(rest_param, operator, result, key):
    param_list = rest_param.split(operator)
    param_list = [x.strip() for x in param_list]
    result[key] = param_list


def prepare_and_generate_aql_for_volpage_filter(search_aql, aql_condition_part, query_param):
    vol_page_number = re.search(r'\d+', query_param['query'])
    if query_param['query'].startswith(constant.CMD_VOLPAGE):
        query = query_param['query'][len(constant.CMD_VOLPAGE):].strip()
        query = format_volpage(query)
        pattern = r"^([asmdASMD])\s"
        replacement = r"\1n "
        query = re.sub(pattern, replacement, query)
        first_part_of_volpage = query.split(' ')[0] if ' ' in query else ''
        possible_volpages = []
        if vol_page_number is not None:
            vol_page_no = re.search(r'\d+', query).group()
            possible_volpages.extend(
                query.split(vol_page_no)[0] + str(i)
                for i in range(int(vol_page_no) - 5, int(vol_page_no) + 4)
                if i > 0
            )
        else:
            possible_volpages.append(query)

        standardized_volpages = standardization_volpage(query)
        if not re.search(r'\d+', standardized_volpages):
            first_part_of_volpage = ''
        possible_volpages.append(standardized_volpages)
        possible_volpages = list(set(possible_volpages))
        search_aql = generate_aql_for_volpage_filter(possible_volpages, first_part_of_volpage)
        query_param['query'] = query
    return query_param, search_aql, aql_condition_part


def generate_aql_for_volpage_filter(possible_volpages, first_part_of_volpage):
    aql = '''
    FOR d IN instant_volpage_search
    SEARCH (PHRASE(d.volpage, @query, "common_text")
        OR PHRASE(d.alt_volpage, @query, "common_text") OR
    '''

    for volpage in possible_volpages:
        aql += (
            f'PHRASE(d.volpage, "{volpage}", "common_text") OR '
            f'PHRASE(d.alt_volpage, "{volpage}", "common_text") OR '
        )
    aql = aql[:-4]

    aql += '''
    )
    SORT d.uid
    '''
    if first_part_of_volpage:
        aql += f' FILTER STARTS_WITH(d.uid, "{first_part_of_volpage.lower()}")'
    aql += '''
    LET translation_title = (
        FOR name IN names
            FILTER name.uid == d.uid AND name.lang == @lang
            LIMIT 1
            RETURN name.name
    )[0]

    LET root_title = (
        FOR name IN names
            FILTER name.uid == d.uid AND name.is_root == True
            LIMIT 1
            RETURN name.name
    )[0]

    LET all_reference = (
        FOR tr IN text_references
        FILTER tr.uid == d.uid
        RETURN tr.volpage
    )[0]

    RETURN {
        acronym: d.acronym,
        uid: d.uid,
        lang: d.lang,
        name: translation_title ? translation_title : root_title,
        volpage: d.volpage,
        alt_volpage: d.alt_volpage,
        all_reference: all_reference,
        content: '',
        segmented_text: '',
    }
    '''

    return aql


def format_volpage(volpage):
    return re.sub(r'[^a-zA-Z0-9]', ' ', volpage)


def standardization_volpage(volpage):
    parts = volpage.split()
    if len(parts) < 3:
        return volpage
    parts[0] = "PTS "
    parts[1] = roman_to_int(parts[1])
    parts[2] = f".{parts[2]}"
    return "{}{}{}".format(*parts)


def roman_to_int(roman):
    roman_dict = {
        "I": 1,
        "V": 5,
        "X": 10,
        "L": 50,
        "C": 100,
        "D": 500,
        "M": 1000
    }
    result = 0
    for i in range(len(roman)):
        if (
            i == len(roman) - 1 or
            roman_dict[roman[i].upper()] >= roman_dict[roman[i + 1].upper()]
        ):
            if roman[i].upper() in roman_dict:
                result += roman_dict[roman[i].upper()]
        elif roman[i].upper() in roman_dict:
            result -= roman_dict[roman[i].upper()]
    return result


def prepare_and_generate_aql_for_reference_filter(search_aql, aql_condition_part, query_param):
    if query_param['query'].startswith(constant.CMD_REFERENCE):
        query = query_param['query'][len(constant.CMD_REFERENCE):].strip()
        search_aql = generate_aql_for_reference_filter(query)
        query_param['query'] = query
    return query_param, search_aql, aql_condition_part


def generate_aql_for_reference_filter(query):
    return '''
        FOR d IN instant_volpage_search
        SEARCH (PHRASE(d.volpage, @query, "common_text")
                OR PHRASE(d.alt_volpage, @query, "common_text"))

        SORT d.uid

        LET translation_title = (
            FOR name IN names
                FILTER name.uid == d.uid AND name.lang == @lang
                LIMIT 1
                RETURN name.name
        )[0]

        LET root_title = (
            FOR name IN names
                FILTER name.uid == d.uid AND name.is_root == True
                LIMIT 1
                RETURN name.name
        )[0]

        LET all_reference = (
            FOR tr IN text_references
            FILTER tr.uid == d.uid
            RETURN tr.volpage
        )[0]

        RETURN {
            acronym: d.acronym,
            uid: d.uid,
            lang: d.lang,
            name: translation_title ? translation_title : root_title,
            all_reference: all_reference,
            content: '',
            segmented_text: '',
        }
        '''
